"""Fixed, read-only queries. No SQL or identifiers are supplied by the model."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.clients.api_gateway_client import GatewayError
from app.core.config import Settings
from app.schemas.user_context import UserContext
from app.services.permission_service import PermissionService


class DatabaseReadError(GatewayError):
    def __init__(self, detail: str):
        super().__init__(503, detail)


class MysqlReadOnlyReader:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def query(self, sql: str, values: tuple[Any, ...]) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._query, sql, values)

    def _query(self, sql: str, values: tuple[Any, ...]) -> list[dict[str, Any]]:
        # Import lazily: disabled fallback does not need a database driver/connection.
        try:
            import pymysql
        except ImportError as exc:
            raise DatabaseReadError('Thiếu PyMySQL; chạy python -m pip install -e ".[test]" trong dự án AI') from exc
        config = self.settings
        try:
            with pymysql.connect(host=config.ai_db_host, port=config.ai_db_port,
                                 user=config.ai_db_user, password=config.ai_db_password.get_secret_value(),
                                 charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                                 connect_timeout=config.ai_db_timeout_seconds,
                                 read_timeout=config.ai_db_timeout_seconds,
                                 write_timeout=config.ai_db_timeout_seconds, autocommit=False,
                                 local_infile=False) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION MAX_EXECUTION_TIME = %s", (config.ai_db_timeout_seconds * 1000,))
                    cursor.execute("SET time_zone = '+07:00'")
                    cursor.execute("START TRANSACTION READ ONLY")
                    cursor.execute(sql, values)
                    rows = cursor.fetchall()
                connection.rollback()
                if len(rows) > config.ai_db_max_rows:
                    raise DatabaseReadError("Dữ liệu vượt giới hạn tra cứu DB; chọn một chi nhánh/phạm vi nhỏ hơn")
                return [{key: self._json_value(value) for key, value in row.items()} for row in rows]
        except pymysql.MySQLError as exc:
            # Never expose connection credentials, raw SQL, schema errors or customer rows.
            raise DatabaseReadError("Không đọc được DB dự phòng; kiểm tra kết nối, view và tài khoản ai_reader") from exc

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value


# View and column names are constants in source, not configurable/model generated.
LIST_READS = {
    "/api/v1/inventory/equipment": ("inventory_db.ai_equipment", "inventory.equipment.read",
        "id, organizationId, branchId, warehouseId, modelId, assetCode, serialNumber, status, conditionStatus, note"),
    "/api/v1/inventory/warehouses": ("inventory_db.ai_warehouses", "inventory.warehouse.read",
        "id, organizationId, branchId, name, active"),
    "/api/v1/quotations": ("rental_db.ai_quotations", "rental.quotation.read",
        "id, organizationId, branchId, quotationCode, rentalRequestId, customerId, status, validUntil, totalAmount"),
    "/api/v1/rental-orders": ("rental_db.ai_rental_orders", "rental.order.read",
        "id, organizationId, branchId, orderCode, quotationId, customerId, status, startAt, endAt"),
    "/api/v1/rental-requests": ("rental_db.ai_rental_requests", "rental.request.read",
        "id, organizationId, branchId, deliveryAddress"),
    "/api/v1/rental-contracts": ("rental_db.ai_rental_contracts", "rental.contract.read",
        "id, organizationId, branchId, contractCode, rentalOrderId, customerId, status, startAt, endAt, totalAmount"),
}


class DatabaseFallbackClient:
    """GET-shaped adapter so existing tools keep one aggregation/formatting implementation."""
    def __init__(self, settings: Settings, context: UserContext, reader=None):
        if not PermissionService.can_use_chat(context):
            raise GatewayError(403, "DB fallback chỉ dành cho Admin/Manager")
        self.settings, self.context = settings, context
        self.reader = reader or MysqlReadOnlyReader(settings)
        self.read_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _permission(self, permission: str):
        if permission not in self.context.permissions:
            raise GatewayError(403, "Không có quyền tra cứu dữ liệu dự phòng này")

    @staticmethod
    def _positive(value: Any) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError("Định danh DB phải là số nguyên dương")
        return value

    def _scope(self, organization_id: Any, branch_id: Any = None, *, all_branches=False):
        org = self._positive(organization_id)
        user = self.context
        if not user.is_admin and org != user.organization_id:
            raise GatewayError(403, "Không được đọc DB ngoài tổ chức được phân công")
        branches = None if all_branches and user.is_admin else user.branch_ids
        if not all_branches:
            branch = self._positive(branch_id)
            if not user.is_admin and branch not in user.branch_ids:
                raise GatewayError(403, "Không được đọc DB ngoài chi nhánh được phân công")
            branches = (branch,)
        if branches == ():
            raise GatewayError(403, "Tài khoản chưa được cấp chi nhánh để đọc DB")
        where, values = "organizationId = %s", [org]
        if branches is not None:
            where += " AND branchId IN (" + ",".join("%s" for _ in branches) + ")"
            values.extend(branches)
        return where, tuple(values)

    async def get(self, endpoint: str, token=None, params=None):
        params = params or {}
        if endpoint in LIST_READS:
            view, permission, columns = LIST_READS[endpoint]
            self._permission(permission)
            where, values = self._scope(params.get("organizationId"), params.get("branchId"),
                                        all_branches=endpoint.endswith("/warehouses"))
            rows = await self.reader.query(f"SELECT {columns} FROM {view} WHERE {where} ORDER BY id LIMIT %s",
                                           (*values, self.settings.ai_db_max_rows + 1))
            if endpoint.endswith("/warehouses"):
                for row in rows:
                    row["active"] = bool(row["active"])
            return rows
        customer = re.fullmatch(r"/api/v1/organizations/([1-9]\d*)/customers/([1-9]\d*)", endpoint)
        if customer:
            self._permission("customer.profile.read")
            org, customer_id = map(int, customer.groups())
            where, values = self._scope(org, all_branches=True)
            rows = await self.reader.query(
                "SELECT id, organizationId, branchId, customerCode, customerType, displayName, "
                "email, phone, address, fullName, companyName, taxCode, status "
                f"FROM organization_customer_db.ai_customers WHERE {where} AND id = %s LIMIT 1",
                (*values, customer_id))
            if not rows:
                raise GatewayError(404, "Không tìm thấy khách hàng trong phạm vi được cấp")
            return rows[0]
        if endpoint == "/api/v1/availability":
            return await self._availability(params)
        raise GatewayError(403, "Endpoint không nằm trong danh sách DB fallback cho phép")

    async def _availability(self, params):
        self._permission("inventory.availability.read")
        where, values = self._scope(params.get("organizationId"), params.get("branchId"))
        type_id = self._positive(params.get("equipmentTypeId"))
        quantity = self._positive(params.get("quantity"))
        try:
            start, end = (datetime.fromisoformat(params[key]) for key in ("startAt", "endAt"))
            if start.tzinfo or end.tzinfo or end <= start:
                raise ValueError()
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Khoảng ngày khả dụng DB phải là giờ Việt Nam, ngày trả sau ngày nhận") from exc
        rows = await self.reader.query(
            "SELECT id FROM inventory_db.ai_available_equipment e "
            f"WHERE {where} AND equipmentTypeId = %s AND NOT EXISTS ("
            "SELECT 1 FROM inventory_db.ai_reservation_blocks b "
            "WHERE b.organizationId = e.organizationId AND b.branchId = e.branchId AND b.equipmentId = e.id "
            "AND b.startAt < %s AND b.endAt > %s "
            "AND (b.status = 'CONFIRMED' OR (b.status = 'HELD' AND (b.expiresAt IS NULL OR b.expiresAt > CURRENT_TIMESTAMP)))) "
            "ORDER BY id LIMIT %s", (*values, type_id, end, start, self.settings.ai_db_max_rows + 1))
        return {"available": len(rows) >= quantity, "availableQuantity": len(rows),
                "requestedQuantity": quantity, "equipmentIds": [row["id"] for row in rows]}

    def sources(self, sources):
        return [{**source, "kind": "DATABASE_FALLBACK", "readAt": self.read_at} for source in sources]
