from __future__ import annotations

import asyncio
import json
from typing import Any

from app.chatbot.conversation_memory import ConversationMemory
from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.clients.ollama_client import OllamaClient
from app.core.config import Settings, get_settings
from app.schemas.user_context import UserContext
from app.services.permission_service import InvalidTokenContext, PermissionService
from app.tools import customer_tools, rental_tools
from app.tools.common import unwrap_gateway_data


class ToolInputError(ValueError):
    pass


class ChatOrchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        ollama: OllamaClient | None = None,
        gateway: ApiGatewayClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.ollama = ollama or OllamaClient(self.settings)
        self.gateway = gateway or ApiGatewayClient(self.settings)
        self.memory = ConversationMemory(self.settings.chat_history_limit)

    async def _authenticate(self, token: str) -> tuple[UserContext, dict[str, Any]]:
        # Đây là bước xác thực thật: Identity Service kiểm chữ ký và thời hạn JWT.
        response = await self.gateway.get("/api/v1/auth/me", token)
        profile = unwrap_gateway_data(response)
        if not isinstance(profile, dict):
            raise GatewayError(502, "Identity Service trả về hồ sơ không hợp lệ")

        try:
            context = PermissionService.extract_user_context(token)
        except InvalidTokenContext as exc:
            raise GatewayError(401, str(exc)) from exc

        profile_user_id = profile.get("userId")
        if profile_user_id is None or int(profile_user_id) != context.user_id:
            raise GatewayError(401, "JWT không khớp với hồ sơ người dùng")
        return context, profile

    @staticmethod
    def _parse_tool_call(raw_response: str) -> tuple[str, dict[str, Any]]:
        try:
            value = json.loads(raw_response)
        except json.JSONDecodeError:
            start = raw_response.find("{")
            end = raw_response.rfind("}")
            if start < 0 or end <= start:
                return "none", {}
            try:
                value = json.loads(raw_response[start : end + 1])
            except json.JSONDecodeError:
                return "none", {}

        if not isinstance(value, dict):
            return "none", {}
        tool_name = value.get("tool", "none")
        params = value.get("params") or {}
        return str(tool_name), params if isinstance(params, dict) else {}

    @staticmethod
    def _param_int(params: dict[str, Any], *names: str) -> int | None:
        for name in names:
            value = params.get(name)
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise ToolInputError(f"{name} phải là số nguyên") from exc
        return None

    def _organization_id(self, context: UserContext, params: dict[str, Any]) -> int:
        requested = self._param_int(params, "organization_id", "organizationId")
        if context.organization_id is not None and not context.is_admin:
            return context.organization_id
        organization_id = requested or context.organization_id
        if organization_id is None:
            raise ToolInputError("Bạn cần nêu organizationId trong câu hỏi")
        return organization_id

    def _branch_ids(self, context: UserContext, params: dict[str, Any]) -> tuple[int, ...]:
        requested = self._param_int(params, "branch_id", "branchId")
        if requested is not None:
            if context.branch_ids and requested not in context.branch_ids and not context.is_admin:
                raise ToolInputError("Bạn không thuộc chi nhánh được yêu cầu")
            return (requested,)
        if context.branch_ids:
            return context.branch_ids
        raise ToolInputError("Bạn cần nêu branchId trong câu hỏi")

    async def _select_tool(
        self,
        message: str,
        context: UserContext,
    ) -> tuple[str, dict[str, Any]]:
        available = PermissionService.available_tools(context)
        descriptions = {
            "get_my_profile": "Xem tài khoản đang đăng nhập; không có tham số.",
            "get_pending_quotations": (
                "Xem báo giá chờ quản lý duyệt; params tùy chọn: "
                "organization_id, branch_id."
            ),
            "get_customer_info": (
                "Xem chi tiết khách hàng; params: customer_id, "
                "organization_id nếu token không có organization."
            ),
        }
        tool_lines = [
            f"- {name}: {descriptions[name]}"
            for name in available
        ]
        system_prompt = (
            "Bạn là bộ định tuyến công cụ, không phải chatbot trả lời.\n"
            "Chỉ chọn một công cụ trong danh sách sau:\n"
            + "\n".join(tool_lines)
            + "\nNếu câu hỏi không cần dữ liệu hệ thống, chọn none. "
            "Chỉ trả về JSON theo mẫu "
            '{"tool":"tên hoặc none","params":{}}. '
            "Không được tạo tên công cụ mới."
        )
        raw = await self.ollama.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            json_format=True,
        )
        return self._parse_tool_call(raw)

    async def _execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: UserContext,
        profile: dict[str, Any],
        token: str,
    ) -> tuple[Any, list[dict[str, str]]]:
        if tool_name == "none":
            return [], []
        if not PermissionService.can_access_tool(context, tool_name):
            raise ToolInputError("Bạn không có permission để dùng chức năng được yêu cầu")

        if tool_name == "get_my_profile":
            return profile, [
                {"service": "identity-service", "endpoint": "/api/v1/auth/me"}
            ]

        organization_id = self._organization_id(context, params)

        if tool_name == "get_pending_quotations":
            branch_ids = self._branch_ids(context, params)
            results = await asyncio.gather(
                *[
                    rental_tools.get_pending_quotations(
                        self.gateway,
                        token,
                        organization_id,
                        branch_id,
                    )
                    for branch_id in branch_ids
                ]
            )
            merged = [quotation for branch in results for quotation in branch]
            return merged, [
                {"service": "rental-service", "endpoint": "/api/v1/quotations"}
            ]

        if tool_name == "get_customer_info":
            requested_customer_id = self._param_int(params, "customer_id", "customerId")
            if "CUSTOMER" in context.roles and context.customer_id is not None:
                customer_id = context.customer_id
            else:
                customer_id = requested_customer_id
            if customer_id is None:
                raise ToolInputError("Bạn cần nêu customerId trong câu hỏi")
            result = await customer_tools.get_customer_info(
                self.gateway,
                token,
                organization_id,
                customer_id,
            )
            return result, [
                {
                    "service": "organization-customer-service",
                    "endpoint": (
                        f"/api/v1/organizations/{organization_id}"
                        f"/customers/{customer_id}"
                    ),
                }
            ]

        raise ToolInputError("Công cụ AI yêu cầu chưa được hỗ trợ")

    @staticmethod
    def _response_data(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    async def handle_message(self, message: str, token: str, conversation_id: str) -> dict[str, Any]:
        context, profile = await self._authenticate(token)
        tool_name, params = await self._select_tool(message, context)

        sources: list[dict[str, str]] = []
        tool_result: Any = []
        tool_error: str | None = None
        try:
            tool_result, sources = await self._execute_tool(
                tool_name,
                params,
                context,
                profile,
                token,
            )
        except ToolInputError as exc:
            tool_error = str(exc)

        system_data = {
            "tool": tool_name,
            "result": tool_result,
            "error": tool_error,
        }
        serialized_data = json.dumps(system_data, ensure_ascii=False, default=str)
        serialized_data = serialized_data[: self.settings.max_tool_result_chars]
        history = await self.memory.get(context.user_id, conversation_id)

        final_prompt = (
            "Bạn là trợ lý tiếng Việt cho hệ thống cho thuê thiết bị. "
            "Dữ liệu nghiệp vụ chỉ được lấy từ SYSTEM_DATA. "
            "Không được bịa số lượng, trạng thái, khách hàng hoặc giao dịch. "
            "Nếu SYSTEM_DATA có error, hãy nói rõ lỗi và thông tin còn thiếu. "
            "Nếu tool là none nhưng câu hỏi cần dữ liệu thời gian thực, hãy nói "
            "chức năng đó chưa được tích hợp. Trả lời ngắn gọn, dễ hiểu.\n"
            f"SYSTEM_DATA={serialized_data}"
        )
        answer = await self.ollama.chat(
            [
                {"role": "system", "content": final_prompt},
                *history,
                {"role": "user", "content": message},
            ]
        )
        await self.memory.add_exchange(
            context.user_id,
            conversation_id,
            message,
            answer,
        )

        return {
            "conversationId": conversation_id,
            "answer": answer,
            "data": self._response_data(tool_result),
            "actions": [],
            "sources": sources,
        }

    async def clear_conversation(self, token: str, conversation_id: str) -> None:
        context, _ = await self._authenticate(token)
        await self.memory.clear(context.user_id, conversation_id)
