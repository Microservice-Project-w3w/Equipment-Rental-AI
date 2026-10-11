from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest

from app.chatbot.orchestrator import ChatOrchestrator, ToolInputError
from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.core.config import Settings
from app.schemas.user_context import UserContext
from app.services.permission_service import PermissionService
from app.tools import billing_tools, inventory_tools, logistics_tools, maintenance_tools

PERMISSIONS = frozenset({
    "inventory.equipment.read", "inventory.warehouse.read", "inventory.availability.read",
    "rental.order.read", "rental.quotation.read", "rental.request.read",
    "rental.contract.read", "customer.profile.read",
})
CONTEXT = UserContext(7, ("MANAGER",), PERMISSIONS, 1, (2,), None)
SETTINGS = Settings(_env_file=None, ollama_model="test-model", api_gateway_base_url="http://gateway.test")


def equipment(id, status, warehouse=10):
    return {"id": id, "organizationId": 1, "branchId": 2, "warehouseId": warehouse,
            "modelId": 9, "assetCode": f"CAM-{id}", "serialNumber": f"SN-{id}",
            "status": status, "conditionStatus": "GOOD", "note": None}


def dataset():
    return {
        "/api/v1/auth/me": {"success": True, "data": {"userId": "7"}},
        "/api/v1/inventory/equipment": [equipment(1, "AVAILABLE"), equipment(2, "MAINTENANCE"),
                                      equipment(3, "DAMAGED", None), equipment(4, "RESERVED")],
        "/api/v1/inventory/warehouses": [
            {"id": 10, "organizationId": 1, "branchId": 2, "name": "Kho A", "active": True},
            {"id": 11, "organizationId": 1, "branchId": 3, "name": "Kho ngoài phạm vi", "active": True}],
        "/api/v1/availability": {"success": True, "data": {"available": False, "availableQuantity": 0, "equipmentIds": []}},
        "/api/v1/rental-orders": {"data": [
            {"id": 1, "organizationId": 1, "branchId": 2, "orderCode": "ORD-1", "status": "CONFIRMED",
             "quotationId": 10, "customerId": 3, "startAt": "2026-10-20T09:00:00", "endAt": "2026-10-24T18:00:00"},
            {"id": 2, "organizationId": 1, "branchId": 2, "status": "CANCELLED", "quotationId": 10,
             "startAt": "2026-10-20T09:00:00", "endAt": "2026-10-24T18:00:00"}]},
        "/api/v1/quotations": {"data": [{"id": 10, "organizationId": 1, "branchId": 2, "rentalRequestId": 20, "status": "SENT"}]},
        "/api/v1/rental-requests": {"data": [{"id": 20, "organizationId": 1, "branchId": 2, "deliveryAddress": "Địa chỉ khách hàng"}]},
        "/api/v1/rental-contracts": {"data": [
            {"id": 1, "organizationId": 1, "branchId": 2, "status": "ACTIVE", "totalAmount": "1000.50"},
            {"id": 2, "organizationId": 1, "branchId": 2, "status": "PENDING_APPROVAL", "totalAmount": "9999"},
            {"id": 3, "organizationId": 1, "branchId": 2, "status": "CANCELLED", "totalAmount": "8888"}]},
    }


def gateway(data=None, token="test-token"):
    calls = []
    data = data if data is not None else dataset()

    async def handler(request):
        assert request.method == "GET"  # No AI business writes.
        assert request.headers["Authorization"] == f"Bearer {token}"
        calls.append(request)
        path = request.url.path
        assert path in data, f"Unknown backend endpoint: {path}"
        if path not in ("/api/v1/auth/me",):
            assert request.url.params["organizationId"] == "1"
            if path != "/api/v1/inventory/warehouses":
                assert request.url.params["branchId"] == "2"
        return httpx.Response(200, json=data[path])

    return ApiGatewayClient(SETTINGS, httpx.MockTransport(handler)), calls


class FakeOllama:
    def __init__(self, tool="get_inventory_stock", params=None):
        self.tool = tool
        self.params = params or {}
        self.calls = []

    async def chat(self, messages, json_format=False):
        self.calls.append((messages, json_format))
        if json_format:
            return json.dumps({"tool": self.tool, "params": self.params})
        return "Đã tra cứu dữ liệu từ API."


def make_chat(tool="get_inventory_stock", params=None, permissions=PERMISSIONS, role="MANAGER"):
    token = jwt.encode({
        "sub": "7", "roles": [role], "organizationId": 1, "branchIds": [2],
        "permissions": list(permissions), "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }, "test-secret-with-at-least-32-bytes-long", algorithm="HS256")
    client, calls = gateway(token=token)
    ollama = FakeOllama(tool, params)
    return ChatOrchestrator(SETTINGS, ollama, client), token, calls, ollama


@pytest.mark.asyncio
async def test_stock_uses_real_scoped_data_and_status_counts():
    client, calls = gateway()
    result = await inventory_tools.get_inventory_stock(client, "test-token", 1, (2,), include_warehouses=True)
    assert result["totalEquipment"] == 4
    assert result["availableInWarehouse"] == 1
    assert result["countsByStatus"]["MAINTENANCE"] == 1
    assert [w["id"] for w in result["warehouses"]] == [10]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_stock_filters_and_list_limits_do_not_change_the_full_count():
    client, _ = gateway()
    result = await inventory_tools.get_inventory_stock(client, "test-token", 1, (2,), status="available", keyword="SN-1")
    assert result["totalEquipment"] == 1
    data = dataset()
    data["/api/v1/inventory/equipment"] = [equipment(i, "AVAILABLE") for i in range(51)]
    client, _ = gateway(data)
    result = await inventory_tools.get_inventory_stock(client, "test-token", 1, (2,))
    assert result["totalEquipment"] == 51
    assert len(result["equipment"]) == 50
    assert result["equipmentListTruncated"] is True


@pytest.mark.asyncio
async def test_maintenance_is_status_only_not_a_maintenance_schedule():
    client, _ = gateway()
    result = await maintenance_tools.get_maintenance_equipment(client, "test-token", 1, (2,))
    assert [e["id"] for e in result["equipment"]] == [2, 3]
    assert result["maintenanceScheduleAvailable"] is False
    assert result["maintenanceTicketsAvailable"] is False


@pytest.mark.asyncio
async def test_availability_uses_rental_public_api_and_preserves_unavailability():
    client, calls = gateway()
    result = await inventory_tools.check_equipment_availability(
        client, "test-token", 1, 2, 9, "2026-10-20T09:00:00", "2026-10-24T18:00:00", 2,
    )
    assert result["available"] is False
    assert result["availableQuantity"] == 0
    assert calls[0].url.path == "/api/v1/availability"
    assert calls[0].url.params["quantity"] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [
    ("2026-10-24T18:00:00", "2026-10-20T09:00:00"),
    ("bad-date", "2026-10-24T18:00:00"),
    ("2026-10-20T09:00:00Z", "2026-10-24T18:00:00Z"),
])
async def test_invalid_availability_dates_do_not_call_backend(start, end):
    client, calls = gateway()
    with pytest.raises(ValueError):
        await inventory_tools.check_equipment_availability(client, "test-token", 1, 2, 9, start, end, 1)
    assert calls == []


@pytest.mark.asyncio
async def test_handover_plan_joins_real_delivery_address_and_excludes_cancelled_orders():
    client, _ = gateway()
    result = await logistics_tools.get_rental_handover_plan(client, "test-token", 1, (2,))
    assert result["totalEvents"] == 2
    assert result["events"][0]["deliveryAddress"] == "Địa chỉ khách hàng"
    assert result["events"][1]["eventType"] == "EXPECTED_RETURN"
    assert result["events"][1]["deliveryAddress"] is None
    assert result["actualDeliveryTrackingAvailable"] is False


@pytest.mark.asyncio
async def test_handover_date_filter_returns_only_due_return_events():
    client, _ = gateway()
    result = await logistics_tools.get_rental_handover_plan(client, "test-token", 1, (2,), from_date="2026-10-22", to_date="2026-10-24")
    assert result["totalEvents"] == 1
    assert result["events"][0]["eventType"] == "EXPECTED_RETURN"


@pytest.mark.asyncio
async def test_contract_values_never_invent_payments_or_debt():
    client, _ = gateway()
    result = await billing_tools.get_contract_values(client, "test-token", 1, (2,))
    assert result["activeContractValue"] == "1000.50"
    assert result["paymentsAvailable"] is False
    assert result["paidAmount"] is None
    assert result["outstandingAmount"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/inventory/equipment", "/api/v1/rental-orders", "/api/v1/rental-contracts"])
async def test_malformed_or_cross_scope_data_is_not_presented_as_valid_empty_data(path):
    data = dataset()
    data[path] = [{"id": 999, "organizationId": 99, "branchId": 2}]
    client, _ = gateway(data)
    with pytest.raises(GatewayError):
        if "equipment" in path:
            await inventory_tools.get_inventory_stock(client, "test-token", 1, (2,))
        elif "orders" in path:
            await logistics_tools.get_rental_handover_plan(client, "test-token", 1, (2,))
        else:
            await billing_tools.get_contract_values(client, "test-token", 1, (2,))


def test_tools_obey_permissions_and_profile_is_no_longer_a_chat_tool():
    assert "get_my_profile" not in PermissionService.available_tools(CONTEXT)
    assert PermissionService.can_access_tool(CONTEXT, "get_inventory_stock")
    restricted = UserContext(7, ("MANAGER",), frozenset({"rental.order.read"}), 1, (2,), None)
    assert not PermissionService.can_access_tool(restricted, "get_rental_handover_plan")


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "abc"])
def test_invalid_identifiers_are_not_coerced_into_valid_ids(value):
    with pytest.raises(ToolInputError):
        ChatOrchestrator._param_int({"branch_id": value}, "branch_id")


@pytest.mark.asyncio
async def test_full_chat_routes_stock_and_returns_data_sources_without_writes():
    chat, token, calls, ollama = make_chat()
    response = await chat.handle_message("Tra cứu tồn kho", token, "conversation-1")
    assert response["data"][0]["totalEquipment"] == 4
    assert response["sources"][0]["endpoint"] == "/api/v1/inventory/equipment"
    assert response["actions"] == []
    assert calls[0].url.path == "/api/v1/auth/me"  # Still required for authentication.
    assert len(ollama.calls) == 2
    assert "get_my_profile" not in ollama.calls[0][0][0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"branch_id": 3}, {"organization_id": 99}])
async def test_chat_denies_scope_escalation_before_inventory_queries(params):
    chat, token, calls, ollama = make_chat(params=params)
    response = await chat.handle_message("Tồn kho", token, "conversation-2")
    assert "không thuộc" in response["answer"]
    assert len(calls) == 1
    assert len(ollama.calls) == 1


@pytest.mark.asyncio
async def test_chat_checks_permission_even_if_model_selects_a_forbidden_tool():
    chat, token, calls, _ = make_chat(permissions=frozenset({"rental.order.read"}))
    response = await chat.handle_message("Tồn kho", token, "conversation-3")
    assert "permission" in response["answer"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_availability_inputs_are_asked_for_not_invented():
    chat, token, calls, _ = make_chat("check_equipment_availability")
    response = await chat.handle_message("Có đủ máy để thuê không?", token, "conversation-4")
    assert "equipmentTypeId" in response["answer"]
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Khách đã thanh toán chưa?", "Hóa đơn số 1 đã trả tiền chưa?", "Công nợ chi nhánh là bao nhiêu?"])
async def test_payment_questions_explicitly_report_missing_backend_without_calling_model(message):
    chat, token, calls, ollama = make_chat("get_contract_values")
    response = await chat.handle_message(message, token, "conversation-5")
    assert "chưa có API" in response["answer"]
    assert response["data"] == []
    assert response["sources"] == []
    assert len(calls) == 1
    assert ollama.calls == []

@pytest.mark.asyncio
@pytest.mark.parametrize("tool,params,field,expected", [
    ("get_maintenance_equipment", {}, "totalEquipment", 2),
    ("get_rental_handover_plan", {"from_date": "2026-10-22", "to_date": "2026-10-24"}, "totalEvents", 1),
    ("get_contract_values", {}, "activeContractValue", "1000.50"),
    ("check_equipment_availability", {"equipment_type_id": 9, "start_at": "2026-10-20T09:00:00",
                                     "end_at": "2026-10-24T18:00:00", "quantity": 2}, "available", False),
])
async def test_new_tool_routes_are_wired_to_chat(tool, params, field, expected):
    chat, token, calls, ollama = make_chat(tool, params)
    result = await chat.handle_message("Tra cứu dữ liệu nghiệp vụ", token, "conversation-7")
    assert result["data"][0][field] == expected
    assert result["sources"]
    assert result["actions"] == []
    assert len(ollama.calls) == 2


@pytest.mark.asyncio
async def test_sales_cannot_access_management_chat():
    chat, token, calls, ollama = make_chat(role="SALES_STAFF")
    with pytest.raises(GatewayError) as error:
        await chat.handle_message("Tồn kho", token, "conversation-6")
    assert error.value.status_code == 403
    assert len(calls) == 1
    assert ollama.calls == []
