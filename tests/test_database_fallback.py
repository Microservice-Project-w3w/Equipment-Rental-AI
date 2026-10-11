from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.clients.database_reader import DatabaseFallbackClient, DatabaseReadError, MysqlReadOnlyReader
from app.core.config import Settings
from app.schemas.chat import ChatResponse
from app.schemas.user_context import UserContext
from tests.test_business_tools import make_chat, CONTEXT, PERMISSIONS, dataset


def config(**overrides):
    return Settings(_env_file=None, ollama_model="test", chat_mode="light", ai_db_fallback_enabled=True,
                    ai_db_password="only-a-test-password", **overrides)

def profile(**overrides):
    return {"userId": "7", "roles": ["MANAGER"], "organizationId": 1, "branchIds": [2],
            "permissions": sorted(PERMISSIONS), **overrides}

def offline_chat(*, status=503, current=None, mode="light", enabled=True):
    chat, token, _, ollama = make_chat()
    chat.settings = config().model_copy(update={"chat_mode": mode, "ai_db_fallback_enabled": enabled})
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"data": current if current is not None else profile()})
        return httpx.Response(status, json={"message": "unavailable"})
    chat.gateway = ApiGatewayClient(chat.settings, httpx.MockTransport(handler))
    return chat, token, calls, ollama

async def stock_rows(sql, values):
    if "ai_equipment" in sql:
        return dataset()["/api/v1/inventory/equipment"]
    if "ai_warehouses" in sql:
        return [dataset()["/api/v1/inventory/warehouses"][0]]
    raise AssertionError(sql)

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_api_outage_reads_scoped_db_and_preserves_metadata_and_vietnamese_warning(status):
    chat, token, calls, ollama = offline_chat(status=status)
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock(side_effect=stock_rows)) as query:
        result = await chat.handle_message("Tồn kho chi nhánh 2", token, "db")
    assert result["data"][0]["totalEquipment"] == 4
    assert "chỉ đọc" in result["answer"] and "4 thiết bị" in result["answer"]
    assert {source["kind"] for source in result["sources"]} == {"DATABASE_FALLBACK"}
    assert all(datetime.fromisoformat(source["readAt"]) for source in result["sources"])
    assert len([call for call in calls if call.url.path == "/api/v1/auth/me"]) == 2
    assert all(args.args[1][:2] == (1, 2) for args in query.call_args_list)
    assert ollama.calls == []
    assert ChatResponse(**result).sources[0].kind == "DATABASE_FALLBACK"

@pytest.mark.asyncio
async def test_natural_mode_keeps_db_warning_even_if_model_omits_it():
    chat, token, _, ollama = offline_chat(mode="natural")
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock(side_effect=stock_rows)):
        result = await chat.handle_message("Tồn kho", token, "natural-db")
    assert len(ollama.calls) == 2
    assert result["answer"].startswith("Lưu ý: API nghiệp vụ không sẵn sàng")

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500])
async def test_business_or_authorization_errors_never_trigger_db(status):
    chat, token, _, _ = offline_chat(status=status)
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        with pytest.raises(GatewayError) as error:
            await chat.handle_message("Tồn kho", token, "blocked")
    assert error.value.status_code == status
    query.assert_not_awaited()

@pytest.mark.asyncio
async def test_invalid_success_payload_is_not_a_database_fallback_trigger():
    chat, token, _, _ = offline_chat(status=200)
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        result = await chat.handle_message("Tồn kho", token, "bad-payload")
    query.assert_not_awaited()
    assert result["data"] == []

@pytest.mark.asyncio
async def test_identity_offline_during_revalidation_does_not_read_database():
    chat, token, _, _ = offline_chat()
    auth_calls = 0
    async def handler(request):
        nonlocal auth_calls
        if request.url.path == "/api/v1/auth/me":
            auth_calls += 1
            return httpx.Response(200, json={"data": profile()}) if auth_calls == 1 else httpx.Response(503)
        return httpx.Response(503)
    chat.gateway = ApiGatewayClient(chat.settings, httpx.MockTransport(handler))
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        with pytest.raises(GatewayError):
            await chat.handle_message("Tồn kho", token, "identity-down")
    query.assert_not_awaited()

@pytest.mark.asyncio
async def test_disabled_fallback_does_not_connect_even_on_outage():
    chat, token, _, _ = offline_chat(enabled=False)
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        result = await chat.handle_message("Tồn kho", token, "disabled")
    query.assert_not_awaited()
    assert result["data"] == []

@pytest.mark.asyncio
async def test_permission_removed_after_jwt_was_issued_denies_database_access():
    chat, token, _, _ = offline_chat(current=profile(permissions=[]))
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        with pytest.raises(GatewayError) as error:
            await chat.handle_message("Tồn kho", token, "revoked")
    query.assert_not_awaited()
    assert error.value.status_code == 403

@pytest.mark.asyncio
async def test_branch_assignment_changed_since_jwt_does_not_read_old_branch():
    chat, token, _, _ = offline_chat(current=profile(branchIds=[3]))
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        result = await chat.handle_message("Tồn kho chi nhánh 2", token, "moved")
    query.assert_not_awaited()
    assert "không thuộc chi nhánh" in result["answer"]

@pytest.mark.asyncio
async def test_old_identity_without_current_permissions_fails_closed():
    chat, token, _, _ = offline_chat(current={"userId": "7", "roles": ["MANAGER"]})
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        with pytest.raises(GatewayError):
            await chat.handle_message("Tồn kho", token, "old-identity")
    query.assert_not_awaited()

@pytest.mark.asyncio
async def test_database_failure_is_not_zero_inventory():
    chat, token, _, _ = offline_chat()
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock(side_effect=DatabaseReadError("DB unavailable"))):
        result = await chat.handle_message("Tồn kho", token, "both-down")
    assert result["data"] == [] and result["sources"] == []
    assert "DB dự phòng chưa đọc được" in result["answer"]
    assert "0 thiết bị" not in result["answer"]

@pytest.mark.asyncio
async def test_successful_api_remains_preferred_and_never_reads_database():
    chat, token, _, _ = make_chat()
    chat.settings = config()
    with patch.object(MysqlReadOnlyReader, "query", AsyncMock()) as query:
        result = await chat.handle_message("Tồn kho", token, "api-up")
    query.assert_not_awaited()
    assert result["data"][0]["totalEquipment"] == 4
    assert all(source.get("kind", "API") == "API" for source in result["sources"])

@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"organizationId": 2, "branchId": 2}, {"organizationId": 1, "branchId": 99}])
async def test_database_adapter_rechecks_scope_independently_of_orchestrator(params):
    reader = type("Reader", (), {"query": AsyncMock()})()
    client = DatabaseFallbackClient(config(), CONTEXT, reader)
    with pytest.raises(GatewayError) as error:
        await client.get("/api/v1/inventory/equipment", params=params)
    assert error.value.status_code == 403
    reader.query.assert_not_awaited()

@pytest.mark.asyncio
async def test_database_customer_query_includes_manager_branch_scope_and_excludes_sensitive_columns():
    reader = type("Reader", (), {"query": AsyncMock(return_value=[{"id": 42}])})()
    client = DatabaseFallbackClient(config(), CONTEXT, reader)
    await client.get("/api/v1/organizations/1/customers/42")
    sql, values = reader.query.call_args.args
    assert "branchId IN (%s)" in sql and values == (1, 2, 42)
    assert "identityNumber" not in sql and "dateOfBirth" not in sql

@pytest.mark.asyncio
async def test_empty_branch_scope_cannot_be_bypassed_by_explicit_branch_id():
    reader = type("Reader", (), {"query": AsyncMock()})()
    user = UserContext(7, ("MANAGER",), PERMISSIONS, 1, (), None)
    client = DatabaseFallbackClient(config(), user, reader)
    for endpoint, params in [("/api/v1/inventory/equipment", {"organizationId": 1, "branchId": 2}),
                             ("/api/v1/organizations/1/customers/42", {})]:
        with pytest.raises(GatewayError):
            await client.get(endpoint, params=params)
    reader.query.assert_not_awaited()

@pytest.mark.asyncio
async def test_availability_uses_fixed_overlap_and_expiration_query():
    reader = type("Reader", (), {"query": AsyncMock(return_value=[{"id": 11}])})()
    client = DatabaseFallbackClient(config(), CONTEXT, reader)
    result = await client.get("/api/v1/availability", params={"organizationId": 1, "branchId": 2,
        "equipmentTypeId": 9, "startAt": "2027-01-01T09:00:00", "endAt": "2027-01-03T09:00:00", "quantity": 2})
    sql, values = reader.query.call_args.args
    assert "b.startAt < %s AND b.endAt > %s" in sql
    assert "b.expiresAt > CURRENT_TIMESTAMP" in sql and "b.status = 'CONFIRMED'" in sql
    assert values[:3] == (1, 2, 9)
    assert result == {"available": False, "availableQuantity": 1, "requestedQuantity": 2, "equipmentIds": [11]}

@pytest.mark.asyncio
async def test_arbitrary_endpoint_or_identifier_is_never_interpreted_as_sql():
    reader = type("Reader", (), {"query": AsyncMock()})()
    client = DatabaseFallbackClient(config(), CONTEXT, reader)
    with pytest.raises(GatewayError):
        await client.get("SELECT * FROM identity_db.users")
    with pytest.raises(ValueError):
        await client.get("/api/v1/inventory/equipment", params={"organizationId": "1 OR 1=1", "branchId": 2})
    reader.query.assert_not_awaited()

@pytest.mark.parametrize("overrides", [{"ai_db_user": "root"}, {"ai_db_password": "short"}])
def test_fallback_configuration_rejects_root_or_missing_secret(overrides):
    values = {"ollama_model": "test", "ai_db_fallback_enabled": True, "ai_db_password": "only-test-password", **overrides}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)

def test_database_reader_starts_readonly_transaction_enforces_timeouts_and_fails_on_row_limit():
    settings = config(ai_db_max_rows=50)
    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [{"id": i} for i in range(51)]
    with patch("pymysql.connect", return_value=connection) as connect:
        with pytest.raises(DatabaseReadError, match="vượt giới hạn"):
            MysqlReadOnlyReader(settings)._query("SELECT id FROM inventory_db.ai_equipment LIMIT %s", (51,))
    commands = [call.args[0] for call in cursor.execute.call_args_list]
    assert commands[:3] == ["SET SESSION MAX_EXECUTION_TIME = %s", "SET time_zone = '+07:00'", "START TRANSACTION READ ONLY"]
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert connect.call_args.kwargs["read_timeout"] == 5
    connection.rollback.assert_called_once()

def test_non_manager_cannot_construct_database_reader_even_with_read_permissions():
    user = UserContext(7, ("SALES_STAFF",), PERMISSIONS, 1, (2,), None)
    with pytest.raises(GatewayError) as error:
        DatabaseFallbackClient(config(), user)
    assert error.value.status_code == 403

@pytest.mark.asyncio
async def test_network_timeout_is_a_fallback_trigger_but_json_parse_error_is_not():
    settings = config()
    async def timeout(request):
        raise httpx.ReadTimeout("test timeout", request=request)
    client = ApiGatewayClient(settings, httpx.MockTransport(timeout))
    with pytest.raises(GatewayError) as error:
        await client.get("/api/v1/inventory/equipment", "token")
    assert error.value.fallback_eligible
    client = ApiGatewayClient(settings, httpx.MockTransport(lambda request: httpx.Response(200, text="not JSON")))
    with pytest.raises(GatewayError) as error:
        await client.get("/api/v1/inventory/equipment", "token")
    assert not error.value.fallback_eligible
