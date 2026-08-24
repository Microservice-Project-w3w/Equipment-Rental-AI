from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt

from app.schemas.user_context import UserContext


class InvalidTokenContext(ValueError):
    pass


class PermissionService:
    """Đọc context sau khi token đã được Identity xác thực qua /auth/me."""

    TOOL_PERMISSIONS = {
        "get_my_profile": None,
        "get_pending_quotations": "rental.quotation.read",
        "get_customer_info": "customer.profile.read",
    }

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise InvalidTokenContext("JWT chứa định danh không hợp lệ") from exc

    @classmethod
    def extract_user_context(cls, token: str) -> UserContext:
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                },
                algorithms=["HS256"],
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenContext("Không đọc được JWT") from exc

        expires_at = claims.get("exp")
        if expires_at is not None and int(expires_at) <= int(datetime.now(timezone.utc).timestamp()):
            raise InvalidTokenContext("JWT đã hết hạn")

        user_id = cls._optional_int(claims.get("userId") or claims.get("sub"))
        if user_id is None:
            raise InvalidTokenContext("JWT thiếu userId")

        raw_roles = claims.get("roles", claims.get("role", []))
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        roles = tuple(str(role).upper() for role in raw_roles)

        raw_permissions = claims.get("permissions", [])
        if isinstance(raw_permissions, str):
            raw_permissions = [raw_permissions]

        raw_branch_ids = claims.get("branchIds", [])
        if raw_branch_ids is None:
            raw_branch_ids = []

        return UserContext(
            user_id=user_id,
            roles=roles,
            permissions=frozenset(str(item) for item in raw_permissions),
            organization_id=cls._optional_int(claims.get("organizationId")),
            branch_ids=tuple(int(item) for item in raw_branch_ids),
            customer_id=cls._optional_int(claims.get("customerId")),
        )

    @classmethod
    def can_access_tool(cls, context: UserContext, tool_name: str) -> bool:
        permission = cls.TOOL_PERMISSIONS.get(tool_name)
        if tool_name not in cls.TOOL_PERMISSIONS:
            return False
        return permission is None or permission in context.permissions

    @classmethod
    def available_tools(cls, context: UserContext) -> list[str]:
        return [
            tool_name
            for tool_name in cls.TOOL_PERMISSIONS
            if cls.can_access_tool(context, tool_name)
        ]
