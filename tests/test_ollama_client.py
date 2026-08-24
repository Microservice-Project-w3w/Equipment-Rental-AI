import json

import httpx
import pytest

from app.clients.ollama_client import OllamaClient
from app.core.config import Settings


@pytest.mark.asyncio
async def test_chat_uses_configured_ollama_model():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["model"] == "my-local-model"
        assert payload["stream"] is False
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Xin chào"}},
        )

    settings = Settings(
        _env_file=None,
        ollama_model="my-local-model",
        ollama_base_url="http://ollama.test",
    )
    client = OllamaClient(settings, httpx.MockTransport(handler))

    answer = await client.chat([{"role": "user", "content": "Chào"}])

    assert answer == "Xin chào"


def test_model_name_accepts_implicit_latest_tag():
    assert OllamaClient.model_is_available(
        "my-local-model",
        ["my-local-model:latest"],
    )
