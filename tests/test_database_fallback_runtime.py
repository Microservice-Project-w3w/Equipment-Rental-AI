"""Opt in with only MySQL + Identity + Gateway online, other business services off."""
import os

import httpx
import pytest

from app.chatbot.orchestrator import ChatOrchestrator
from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.core.config import Settings

pytestmark = pytest.mark.skipif(os.environ.get("RUN_AI_FALLBACK_LIVE") != "1", reason="Requires Identity/Gateway, offline business services and configured reader")

class NoModel:
    async def chat(self, *args, **kwargs):
        raise AssertionError("Runtime fallback test must not call Ollama")

@pytest.mark.asyncio
async def test_real_identity_and_gateway_allow_db_lookups_without_business_services():
    settings = Settings(chat_mode="light", api_gateway_base_url="http://localhost:8080")
    assert settings.ai_db_fallback_enabled, "Configure AI .env before opting in"
    async with httpx.AsyncClient(base_url=settings.api_gateway_base_url, timeout=10) as http:
        login = await http.post("/api/v1/auth/login", json={"email": "rentai.demo.manager@gmail.com", "password": "Demo@123"})
        login.raise_for_status()
        token = login.json()["data"]["accessToken"]
        headers = {"Authorization": "Bearer " + token}
        try:
            me = await http.get("/api/v1/auth/me", headers=headers)
            me.raise_for_status()
            profile = me.json()["data"]
            assert profile["permissions"] and profile["branchIds"] and profile["organizationId"]
            branch = profile["branchIds"][0]
            chat = ChatOrchestrator(settings, NoModel(), ApiGatewayClient(settings))
            for question in (f"Tồn kho chi nhánh {branch}", f"Tổng giá trị hợp đồng chi nhánh {branch}",
                             "Khách hàng ID 2",
                             f"Báo giá chờ duyệt chi nhánh {branch}",
                             f"Lịch trống chi nhánh {branch}, equipmentTypeId=1, 2036-01-02T09:00 đến 2036-01-04T17:00, số lượng 1"):
                result = await chat.handle_message(question, token, "runtime-fallback-test")
                assert result["sources"], result["answer"]
                assert all(source["kind"] == "DATABASE_FALLBACK" for source in result["sources"])
                assert "chỉ đọc" in result["answer"]
            response = await http.post("/api/v1/auth/logout", headers=headers)
            response.raise_for_status()
            with pytest.raises(GatewayError) as error:
                await chat.handle_message("Tồn kho", token, "after-logout")
            assert error.value.status_code == 401
        finally:
            await http.post("/api/v1/auth/logout", headers=headers)
