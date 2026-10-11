from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.chatbot.conversation_memory import ConversationMemory
from app.chatbot.light_router import select_light_tool
from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.core.config import Settings
from app.api.routes import health
from tests.test_business_tools import make_chat

def light_chat(services="inventory"):
    chat, token, calls, ollama = make_chat()
    chat.settings = chat.settings.model_copy(update={"chat_mode": "light", "chat_enabled_services": services})
    return chat, token, calls, ollama

@pytest.mark.asyncio
async def test_inventory_only_needs_identity_and_inventory_not_model_or_other_services():
    chat, token, calls, ollama = light_chat()
    result = await chat.handle_message("Tồn kho chi nhánh 2", token, "light-stock")
    assert result["data"][0]["totalEquipment"] == 4
    assert "4 thiết bị" in result["answer"]
    assert ollama.calls == []
    assert {call.url.path for call in calls} == {"/api/v1/auth/me", "/api/v1/inventory/equipment", "/api/v1/inventory/warehouses"}

@pytest.mark.asyncio
async def test_disabled_function_is_explained_without_calling_that_service():
    chat, token, calls, ollama = light_chat()
    result = await chat.handle_message("Báo giá chờ duyệt", token, "disabled")
    assert "đang tắt" in result["answer"] and "rental" in result["answer"]
    assert result["data"] == [] and result["sources"] == []
    assert [call.url.path for call in calls] == ["/api/v1/auth/me"]
    assert ollama.calls == []

@pytest.mark.asyncio
async def test_rental_only_can_read_contract_values_without_inventory_or_customer_service():
    chat, token, calls, ollama = light_chat("rental")
    result = await chat.handle_message("Tổng giá trị hợp đồng đang hiệu lực", token, "rental-only")
    assert result["data"][0]["activeContractValue"] == "1000.50"
    assert {call.url.path for call in calls} == {"/api/v1/auth/me", "/api/v1/rental-contracts"}
    assert ollama.calls == []

@pytest.mark.asyncio
async def test_offline_service_is_not_reported_as_zero_inventory():
    chat, token, calls, ollama = light_chat()
    async def handler(request):
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"data": {"userId": "7"}})
        return httpx.Response(503, json={"message": "offline"})
    chat.gateway = ApiGatewayClient(chat.settings, httpx.MockTransport(handler))
    result = await chat.handle_message("Tồn kho", token, "offline")
    assert "Chưa lấy được dữ liệu" in result["answer"]
    assert "0 thiết bị" not in result["answer"]
    assert result["data"] == [] and result["sources"] == []
    assert ollama.calls == []

@pytest.mark.asyncio
async def test_removed_manager_role_is_denied_even_with_an_old_manager_jwt():
    chat, token, calls, ollama = light_chat()
    chat.gateway = ApiGatewayClient(chat.settings, httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": {"userId": "7", "roles": ["SALES_STAFF"]}})))
    with pytest.raises(GatewayError) as error:
        await chat.handle_message("Tồn kho", token, "role-revoked")
    assert error.value.status_code == 403
    assert ollama.calls == []

@pytest.mark.asyncio
async def test_identity_unavailable_never_falls_back_to_unverified_jwt():
    chat, token, calls, ollama = light_chat()
    chat.gateway = ApiGatewayClient(chat.settings, httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(GatewayError):
        await chat.handle_message("Tồn kho", token, "no-auth")
    assert ollama.calls == []

@pytest.mark.asyncio
async def test_light_mode_preserves_branch_scope_checks():
    chat, token, calls, ollama = light_chat()
    result = await chat.handle_message("Tồn kho chi nhánh 999", token, "scope")
    assert "không thuộc chi nhánh" in result["answer"]
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_light_mode_unknown_question_explains_limits_not_fake_answer():
    chat, token, calls, ollama = light_chat()
    result = await chat.handle_message("Đặt thuê cho tôi 20 máy", token, "no-write")
    assert "chế độ tra cứu nhẹ" in result["answer"]
    assert len(calls) == 1 and ollama.calls == []

@pytest.mark.asyncio
async def test_capabilities_reveal_configuration_not_a_claim_about_process_health():
    chat, token, calls, ollama = light_chat()
    result = await chat.capabilities(token)
    assert result["mode"] == "light" and result["modelRequired"] is False
    tools = {tool["name"]: tool for tool in result["tools"]}
    assert tools["get_inventory_stock"]["enabled"] is True
    assert tools["check_equipment_availability"]["enabled"] is False
    assert tools["check_equipment_availability"]["requires"] == ["inventory", "rental"]
    assert len(calls) == 1 and ollama.calls == []

@pytest.mark.parametrize("question,tool", [
    ("Thiết bị nào đang bảo trì hoặc hư hỏng?", "get_maintenance_equipment"),
    ("Các đơn nào sắp đến ngày trả thiết bị trong 7 ngày tới?", "get_rental_handover_plan"),
    ("Có những báo giá nào đang chờ duyệt?", "get_pending_quotations"),
    ("Khách hàng ID 42", "get_customer_info"),
    ("Kiểm tra lịch trống equipmentTypeId=9, 2027-01-02T09:00 đến 2027-01-04T17:00, số lượng 2", "check_equipment_availability"),
])
def test_common_demo_questions_route_without_a_model(question, tool):
    assert select_light_tool(question)[0] == tool

def test_availability_extracts_explicit_parameters_without_guessing_ids():
    _, params = select_light_tool("Lịch trống equipmentTypeId=9, chi nhánh 2, 2027-01-02T09:00 đến 2027-01-04T17:00, số lượng 2")
    assert params == {"equipment_type_id": 9, "branch_id": 2, "quantity": 2,
                      "start_at": "2027-01-02T09:00", "end_at": "2027-01-04T17:00"}
    assert "equipment_type_id" not in select_light_tool("Lịch trống máy ảnh")[1]
    with pytest.raises(ValueError):
        select_light_tool("Tồn kho chi nhánh 2 và chi nhánh 3")

def test_next_seven_days_has_exact_calendar_boundaries():
    _, params = select_light_tool("Kế hoạch nhận trả trong 7 ngày tới")
    today = datetime.now(timezone(timedelta(hours=7))).date()
    assert params["from_date"] == today.isoformat()
    assert params["to_date"] == (today + timedelta(days=6)).isoformat()

def test_invalid_service_configuration_fails_fast():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_model="test", chat_enabled_services="billing")

@pytest.mark.asyncio
async def test_unknown_memory_reads_do_not_allocate_and_ttl_expires_history():
    now = [0.0]
    memory = ConversationMemory(4, max_conversations=2, ttl_seconds=60, clock=lambda: now[0])
    for i in range(10):
        assert await memory.get(7, str(i)) == []
    assert not memory._messages
    await memory.add_exchange(7, "a", "Q", "A")
    assert await memory.get(8, "a") == []
    now[0] = 61
    assert await memory.get(7, "a") == []

@pytest.mark.asyncio
async def test_memory_evicts_least_recently_used_conversation():
    memory = ConversationMemory(4, max_conversations=2)
    await memory.add_exchange(7, "a", "Q1", "A1")
    await memory.add_exchange(7, "b", "Q2", "A2")
    await memory.get(7, "a")
    await memory.add_exchange(7, "c", "Q3", "A3")
    assert await memory.get(7, "b") == []
    assert len(await memory.get(7, "a")) == 2
    await memory.clear(7, "a")
    assert await memory.get(7, "a") == []

@pytest.mark.asyncio
async def test_light_health_skips_ollama_entirely(monkeypatch):
    monkeypatch.setattr(health, "settings", health.settings.model_copy(update={"chat_mode": "light"}))
    with patch.object(health.OllamaClient, "check_health", AsyncMock(side_effect=AssertionError("must not call Ollama"))) as model, patch.object(health.ApiGatewayClient, "check_health", AsyncMock(return_value={"status": "UP"})):
        result = await health.dependencies_health()
    assert result["status"] == "UP"
    assert result["dependencies"]["ollama"]["status"] == "SKIPPED"
    model.assert_not_awaited()
