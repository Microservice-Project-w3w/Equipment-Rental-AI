from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings, get_settings


class GatewayError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ApiGatewayClient:
    """HTTP client duy nhất được phép dùng để gọi backend nghiệp vụ."""

    _ALLOWED_PREFIXES = ("/api/v1/", "/gateway/health/")

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        config = settings or get_settings()
        self.base_url = config.api_gateway_base_url.rstrip("/")
        self.timeout = config.api_gateway_timeout_seconds
        self.transport = transport

    @classmethod
    def _validate_endpoint(cls, endpoint: str) -> str:
        parsed = urlsplit(endpoint)
        if parsed.scheme or parsed.netloc:
            raise ValueError("Tool chỉ được truyền path, không được truyền URL đầy đủ")

        path = parsed.path
        if not path.startswith("/") or ".." in path:
            raise ValueError("Gateway path không hợp lệ")
        if path.startswith("/internal/"):
            raise ValueError("AI service không được gọi endpoint /internal/**")
        if not path.startswith(cls._ALLOWED_PREFIXES):
            raise ValueError(f"Endpoint không thuộc API Gateway allowlist: {path}")
        return endpoint

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def request(
        self,
        method: str,
        endpoint: str,
        token: str | None = None,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        safe_endpoint = self._validate_endpoint(endpoint)
        url = f"{self.base_url}{safe_endpoint}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(token),
                    params=params,
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise GatewayError(
                503,
                f"Không thể kết nối API Gateway tại {self.base_url}",
            ) from exc

        if response.is_error:
            detail = f"API Gateway trả về HTTP {response.status_code}"
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = body.get("message") or body.get("detail") or detail
            except ValueError:
                pass
            raise GatewayError(response.status_code, detail)

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise GatewayError(502, "Backend trả về dữ liệu không phải JSON") from exc

    async def get(
        self,
        endpoint: str,
        token: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self.request("GET", endpoint, token, params=params)

    async def post(self, endpoint: str, token: str, payload: dict[str, Any]) -> Any:
        return await self.request("POST", endpoint, token, payload=payload)

    async def put(self, endpoint: str, token: str, payload: dict[str, Any]) -> Any:
        return await self.request("PUT", endpoint, token, payload=payload)

    async def patch(self, endpoint: str, token: str, payload: dict[str, Any] | None = None) -> Any:
        return await self.request("PATCH", endpoint, token, payload=payload)

    async def delete(self, endpoint: str, token: str) -> Any:
        return await self.request("DELETE", endpoint, token)

    async def check_health(self) -> dict[str, Any]:
        return await self.get("/gateway/health/identity")
