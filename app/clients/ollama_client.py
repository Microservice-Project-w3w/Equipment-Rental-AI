from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        config = settings or get_settings()
        self.base_url = config.ollama_base_url.rstrip("/")
        self.model = config.ollama_model
        self.timeout = config.ollama_timeout_seconds
        self.transport = transport

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.RequestError as exc:
            raise OllamaError(f"Không thể kết nối Ollama tại {self.base_url}") from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaError(f"Ollama trả về HTTP {exc.response.status_code}") from exc
        except ValueError as exc:
            raise OllamaError("Ollama trả về dữ liệu không phải JSON") from exc

    async def chat(self, messages: list[dict[str, str]], json_format: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if json_format:
            payload["format"] = "json"

        data = await self._request("POST", "/api/chat", payload)
        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama không trả về nội dung phản hồi")
        return content.strip()

    async def list_models(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/tags")
        models = data.get("models", [])
        return models if isinstance(models, list) else []

    @staticmethod
    def model_is_available(configured_model: str, installed_models: list[str]) -> bool:
        if configured_model in installed_models:
            return True
        if ":" not in configured_model:
            return f"{configured_model}:latest" in installed_models
        return False

    async def check_health(self) -> dict[str, Any]:
        models = await self.list_models()
        names = [item.get("name") for item in models if item.get("name")]
        return {
            "status": "UP",
            "configuredModel": self.model,
            "modelAvailable": self.model_is_available(self.model, names),
            "models": names,
        }
