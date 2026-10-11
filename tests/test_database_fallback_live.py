"""Opt-in local MySQL tests. No Ollama or Java business services required.
Creates only a temporary ai_fb_test_* account and its own reservation fixture.
"""
import os
from pathlib import Path
import runpy
import secrets
import sys
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from dotenv import dotenv_values

from app.clients.database_reader import DatabaseFallbackClient, MysqlReadOnlyReader
from app.core.config import Settings
from app.schemas.user_context import UserContext
from tests.test_business_tools import PERMISSIONS

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_FALLBACK_TESTS") != "1", reason="Requires explicit local DB opt-in")

@pytest.fixture(scope="module")
def database(tmp_path_factory):
    import pymysql
    backend_env = Path(os.environ.get("AI_TEST_BACKEND_ENV", "/home/thaibinh/backend_microservice/.env"))
    backend = dotenv_values(backend_env)
    user = "ai_fb_test_" + uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    host = backend.get("MYSQL_HOST") or "127.0.0.1"
    port = int(backend.get("MYSQL_PORT") or "3307")
    env_file = tmp_path_factory.mktemp("db-fallback") / ".env"
    env_file.write_text(f"AI_DB_HOST={host}\nAI_DB_PORT={port}\nAI_DB_USER={user}\nAI_DB_PASSWORD={password}\n", encoding="utf-8")
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/setup_db_fallback.py"))
    saved_argv = sys.argv
    try:
        sys.argv = ["setup_db_fallback.py", "--backend-env", str(backend_env), "--ai-env", str(env_file)]
        module["main"]()
    finally:
        sys.argv = saved_argv
    config = Settings(_env_file=None, ollama_model="test", ai_db_fallback_enabled=True,
        ai_db_host=host, ai_db_port=port, ai_db_user=user, ai_db_password=password)
    root = pymysql.connect(host=host, port=port, user="root", password=backend["MYSQL_ROOT_PASSWORD"],
                           charset="utf8mb4", autocommit=True, cursorclass=pymysql.cursors.DictCursor)
    try:
        yield config, root
    finally:
        with root.cursor() as cursor:
            cursor.execute("DROP USER %s@'%%'", (user,))
        root.close()
        env_file.unlink()

@pytest.mark.asyncio
async def test_views_read_inventory_rental_and_customer_without_business_services(database):
    config, root = database
    user = UserContext(1, ("ADMIN",), PERMISSIONS, 1, (1,), None)
    client = DatabaseFallbackClient(config, user)
    for path in ("/api/v1/inventory/equipment", "/api/v1/inventory/warehouses", "/api/v1/quotations",
                 "/api/v1/rental-orders", "/api/v1/rental-requests", "/api/v1/rental-contracts"):
        rows = await client.get(path, params={"organizationId": 1, "branchId": 1})
        assert isinstance(rows, list)
        assert all(row["organizationId"] == 1 for row in rows)
        if not path.endswith("/warehouses"):
            assert all(row["branchId"] == 1 for row in rows)
    with root.cursor() as cursor:
        cursor.execute("SELECT id FROM organization_customer_db.ai_customers WHERE organizationId=1 LIMIT 1")
        customer = cursor.fetchone()
    assert customer, "Demo seed needs a customer"
    result = await client.get(f"/api/v1/organizations/1/customers/{customer['id']}")
    assert "identityNumber" not in result and result["organizationId"] == 1

@pytest.mark.asyncio
async def test_reader_cannot_read_base_tables_identity_or_write_views(database):
    import pymysql
    config, _ = database
    with pymysql.connect(host=config.ai_db_host, port=config.ai_db_port, user=config.ai_db_user,
                         password=config.ai_db_password.get_secret_value(), autocommit=False) as connection:
        with connection.cursor() as cursor:
            for sql in ("SELECT id FROM identity_db.users LIMIT 0", "SELECT id FROM inventory_db.equipment LIMIT 0",
                        "UPDATE inventory_db.ai_equipment SET note='not-written' WHERE 1=0"):
                with pytest.raises(pymysql.MySQLError) as error:
                    cursor.execute(sql)
                assert error.value.args[0] in (1044, 1142, 1143)
        connection.rollback()

@pytest.mark.asyncio
async def test_availability_excludes_live_holds_but_ignores_expired_holds_without_scheduler(database):
    config, root = database
    with root.cursor() as cursor:
        cursor.execute("SELECT id, organizationId, branchId, equipmentTypeId FROM inventory_db.ai_available_equipment LIMIT 1")
        gear = cursor.fetchone()
    assert gear, "Demo seed needs an AVAILABLE item in an active warehouse/model/type"
    context = UserContext(1, ("ADMIN",), PERMISSIONS, gear["organizationId"], (gear["branchId"],), None)
    client = DatabaseFallbackClient(config, context)
    start, end = datetime(2036, 1, 2, 9), datetime(2036, 1, 4, 17)
    params = {"organizationId": gear["organizationId"], "branchId": gear["branchId"],
              "equipmentTypeId": gear["equipmentTypeId"], "startAt": start.isoformat(), "endAt": end.isoformat(), "quantity": 1}
    before = await client.get("/api/v1/availability", params=params)
    assert gear["id"] in before["equipmentIds"]
    reference = "AI-FB-AUDIT-" + uuid4().hex
    reservation_id = None
    try:
        with root.cursor() as cursor:
            cursor.execute("INSERT INTO inventory_db.equipment_reservations "
                "(organization_id,branch_id,reservation_code,request_reference,start_at,end_at,expires_at,status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'HELD')", (gear["organizationId"], gear["branchId"], reference,
                    reference, start, end, datetime(2000,1,1)))
            reservation_id = cursor.lastrowid
            cursor.execute("INSERT INTO inventory_db.equipment_reservation_items "
                "(reservation_id,equipment_type_id,equipment_id,start_at,end_at) VALUES (%s,%s,%s,%s,%s)",
                (reservation_id, gear["equipmentTypeId"], gear["id"], start, end))
        expired = await client.get("/api/v1/availability", params=params)
        assert expired == before
        with root.cursor() as cursor:
            cursor.execute("UPDATE inventory_db.equipment_reservations SET expires_at=%s WHERE id=%s AND request_reference=%s",
                (datetime(2037,1,1), reservation_id, reference))
        held = await client.get("/api/v1/availability", params=params)
        assert gear["id"] not in held["equipmentIds"]
        assert held["availableQuantity"] == before["availableQuantity"] - 1
        with root.cursor() as cursor:
            cursor.execute("UPDATE inventory_db.equipment_reservations SET status='CONFIRMED', expires_at=%s WHERE id=%s AND request_reference=%s",
                (datetime(2000,1,1), reservation_id, reference))
        assert gear["id"] not in (await client.get("/api/v1/availability", params=params))["equipmentIds"]
        # Adjacent intervals do not overlap.
        params.update(startAt=end.isoformat(), endAt=(end + timedelta(days=1)).isoformat())
        assert gear["id"] in (await client.get("/api/v1/availability", params=params))["equipmentIds"]
    finally:
        if reservation_id:
            with root.cursor() as cursor:
                cursor.execute("DELETE FROM inventory_db.equipment_reservations WHERE id=%s AND request_reference=%s",
                               (reservation_id, reference))
