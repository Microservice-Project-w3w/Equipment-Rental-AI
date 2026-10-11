from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.chatbot.response_generator import fallback_answer, is_natural_answer
from app.clients.ollama_client import OllamaError
from app.services.chat_limiter import ChatLimiter, ChatLimitError
from app.api.routes import chat as chat_route
from app.main import app
from tests.test_business_tools import make_chat


@pytest.mark.parametrize("raw", [
    '<functioncall> {"tool":"check_equipment_availability","result":{}}',
    '{"available":true}', '[]', 'SYSTEM_DATA={"tool":"get_inventory_stock"}',
    chr(96) * 3 + 'json\n{"totalEquipment":4}\n' + chr(96) * 3,
    'Kết quả: {"tool": "get_inventory_stock", "result": {}}', '',
])
def test_technical_model_output_is_not_a_user_answer(raw):
    assert not is_natural_answer(raw)


def test_natural_vietnamese_is_preserved():
    assert is_natural_answer("Hiện có 4 thiết bị trong chi nhánh của bạn.")


@pytest.mark.asyncio
async def test_raw_functioncall_is_replaced_by_verified_inventory_summary():
    orchestrator, token, calls, ollama = make_chat()
    original = ollama.chat
    async def chat(messages, json_format=False):
        if json_format:
            return await original(messages, True)
        return '<functioncall> {"tool":"get_inventory_stock","result":{"totalEquipment":999}}'
    ollama.chat = chat
    response = await orchestrator.handle_message("Tồn kho", token, "fallback")
    assert "4 thiết bị" in response["answer"]
    assert "999" not in response["answer"]
    assert "functioncall" not in response["answer"]
    assert response["data"][0]["totalEquipment"] == 4
    assert response["sources"][0]["service"] == "inventory-service"


@pytest.mark.asyncio
async def test_narration_failure_preserves_successful_api_lookup():
    orchestrator, token, calls, ollama = make_chat()
    original = ollama.chat
    async def chat(messages, json_format=False):
        if json_format:
            return await original(messages, True)
        raise OllamaError("Ollama timed out")
    ollama.chat = chat
    response = await orchestrator.handle_message("Tồn kho", token, "model-timeout")
    assert "4 thiết bị" in response["answer"]
    assert response["data"][0]["totalEquipment"] == 4


@pytest.mark.asyncio
async def test_routing_failure_is_not_fabricated_as_successful_lookup():
    orchestrator, token, calls, ollama = make_chat()
    async def fail(*args, **kwargs):
        raise OllamaError("Ollama down")
    ollama.chat = fail
    with pytest.raises(OllamaError):
        await orchestrator.handle_message("Tồn kho", token, "routing-failure")
    assert len(calls) == 1  # Identity only, no fabricated business result.


def test_availability_fallback_never_claims_a_reservation_or_sufficient_stock():
    answer = fallback_answer("check_equipment_availability", {
        "equipmentTypeId": 2, "available": False, "requestedQuantity": 3,
        "availableQuantity": 1, "startAt": "2026-10-20T09:00:00", "endAt": "2026-10-24T18:00:00",
    })
    assert "Chưa đủ" in answer
    assert "3 thiết bị" in answer
    assert "là 1" in answer
    assert "chưa tạo đơn hay giữ chỗ" in answer


@pytest.mark.parametrize("tool,data,expected", [
    ("get_pending_quotations", [], "không có báo giá"),
    ("get_pending_quotations", [{"id": 8, "quotationCode": "QUO-8"}], "QUO-8"),
    ("get_customer_info", {"displayName": "Khách Demo", "phone": "0901234567"}, "Khách Demo"),
    ("get_maintenance_equipment", {"totalEquipment": 0, "equipment": []}, "chưa có lịch bảo trì"),
    ("get_contract_values", {"totalContracts": 2, "activeContractValue": "1000.50"}, "1.000,5 VND"),
    ("get_rental_handover_plan", {"totalEvents": 0}, "Không có mốc"),
    ("get_rental_handover_plan", {"totalEvents": 1, "events": [{
        "orderId": 8, "eventType": "EXPECTED_RETURN", "scheduledAt": "2026-10-24T18:00:00"
    }]}, "không phải xác nhận đã giao"),
    ("none", [], "Xin chào"),
])
def test_all_seven_tools_have_readable_fallbacks(tool, data, expected):
    answer = fallback_answer(tool, data)
    assert expected in answer
    assert is_natural_answer(answer)


@pytest.mark.asyncio
async def test_limits_are_per_user_and_expire_without_waiting():
    now = [0.0]
    limiter = ChatLimiter(requests=2, window_seconds=60, clock=lambda: now[0])
    for _ in range(2):
        async with limiter.acquire(7):
            pass
    with pytest.raises(ChatLimitError) as exc:
        async with limiter.acquire(7):
            pass
    assert exc.value.retry_after == 60
    async with limiter.acquire(8):
        pass
    now[0] = 61
    async with limiter.acquire(7):
        pass


@pytest.mark.asyncio
async def test_only_one_inference_can_run_and_capacity_is_released_after_error():
    limiter = ChatLimiter(max_concurrent=1)
    with pytest.raises(RuntimeError, match="test failure"):
        async with limiter.acquire(7):
            with pytest.raises(ChatLimitError):
                async with limiter.acquire(8):
                    pass
            with pytest.raises(ChatLimitError):
                async with limiter.acquire(7):
                    pass
            raise RuntimeError("test failure")
    async with limiter.acquire(8):
        pass


@pytest.mark.asyncio
async def test_cancellation_releases_capacity():
    limiter = ChatLimiter()
    entered = asyncio.Event()
    async def work():
        async with limiter.acquire(7):
            entered.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(work())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with limiter.acquire(8):
        pass


@pytest.mark.parametrize("body", [
    {"message": "   "}, {"message": {"text": "Xin chào"}},
    {"message": "Xin chào", "conversationId": "   "},
    {"message": "Xin chào", "conversationId": ["conversation"]},
])
def test_invalid_chat_body_is_rejected_before_authentication_or_model(body):
    response = TestClient(app).post("/api/v1/chat", json=body,
                                    headers={"Authorization": "Bearer fake-token"})
    assert response.status_code == 422


def test_http_rate_limit_includes_retry_after(monkeypatch):
    class BusyChat:
        async def handle_message(self, **kwargs):
            raise ChatLimitError("Trợ lý đang bận", 5)
    monkeypatch.setattr(chat_route, "orchestrator", BusyChat())
    response = TestClient(app).post("/api/v1/chat", json={"message": "Tồn kho"},
                                    headers={"Authorization": "Bearer fake-token"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "5"
