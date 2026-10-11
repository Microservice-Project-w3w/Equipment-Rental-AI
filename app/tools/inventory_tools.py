from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
from typing import Any

from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.tools.common import unwrap_gateway_data

EQUIPMENT_STATUSES = frozenset({
    "AVAILABLE", "RESERVED", "CHECKED_OUT", "IN_TRANSIT", "INSPECTION",
    "MAINTENANCE", "LOST", "DAMAGED", "RETIRED",
})


def require_list(response: Any) -> list[dict[str, Any]]:
    data = unwrap_gateway_data(response)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise GatewayError(502, "Backend trả về danh sách không hợp lệ")
    return data


async def get_inventory_stock(
    client: ApiGatewayClient, token: str, organization_id: int,
    branch_ids: tuple[int, ...], *, warehouse_id: int | None = None,
    status: str | None = None, keyword: str = "", maintenance_only: bool = False,
    include_warehouses: bool = False,
) -> dict[str, Any]:
    groups = await asyncio.gather(*[
        client.get("/api/v1/inventory/equipment", token, params={
            "organizationId": organization_id, "branchId": branch_id,
        })
        for branch_id in branch_ids
    ])
    equipment_by_id = {}
    for group in groups:
        for item in require_list(group):
            if item.get("organizationId") != organization_id or item.get("branchId") not in branch_ids:
                raise GatewayError(502, "Inventory trả dữ liệu ngoài phạm vi yêu cầu")
            equipment_by_id[item["id"]] = item
    equipment = list(equipment_by_id.values())
    if status:
        status = status.upper()
        if status not in EQUIPMENT_STATUSES:
            raise ValueError("Trạng thái thiết bị không hợp lệ")
        equipment = [e for e in equipment if e.get("status") == status]
    if warehouse_id is not None:
        equipment = [e for e in equipment if e.get("warehouseId") == warehouse_id]
    if maintenance_only:
        equipment = [e for e in equipment if e.get("status") in {"MAINTENANCE", "DAMAGED", "INSPECTION"}]
    if keyword:
        query = keyword.casefold()
        equipment = [e for e in equipment if query in " ".join(
            str(e.get(field) or "") for field in ("assetCode", "serialNumber", "note")
        ).casefold()]
    equipment.sort(key=lambda e: e["id"])
    warehouses = []
    if include_warehouses:
        warehouses = [w for w in require_list(await client.get(
            "/api/v1/inventory/warehouses", token,
            params={"organizationId": organization_id},
        )) if w.get("organizationId") == organization_id and w.get("branchId") in branch_ids]
    fields = ("id", "branchId", "warehouseId", "modelId", "assetCode",
              "serialNumber", "status", "conditionStatus", "note")
    return {
        "organizationId": organization_id,
        "branchIds": list(branch_ids),
        "totalEquipment": len(equipment),
        "countsByStatus": dict(Counter(e.get("status", "UNKNOWN") for e in equipment)),
        "availableInWarehouse": sum(
            e.get("status") == "AVAILABLE" and e.get("warehouseId") is not None
            for e in equipment
        ),
        "warehouses": [{"id": w["id"], "branchId": w["branchId"], "name": w["name"], "active": w.get("active")} for w in warehouses],
        "equipment": [{field: e.get(field) for field in fields} for e in equipment[:50]],
        "equipmentListTruncated": len(equipment) > 50,
        "note": "Số liệu theo trạng thái hiện tại được ghi nhận trong Inventory, không phải kiểm kê thực tế. Khả dụng cho khoảng ngày thuê phải kiểm tra bằng API availability.",
    }


async def check_equipment_availability(
    client: ApiGatewayClient, token: str, organization_id: int, branch_id: int,
    equipment_type_id: int, start_at: str, end_at: str, quantity: int,
) -> dict[str, Any]:
    try:
        start, end = datetime.fromisoformat(start_at), datetime.fromisoformat(end_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cần ngày giờ ISO, ví dụ 2026-10-20T09:00:00") from exc
    if start.tzinfo is not None or end.tzinfo is not None:
        raise ValueError("Dùng ngày giờ Việt Nam không kèm múi giờ/Z")
    if end <= start:
        raise ValueError("Ngày trả phải sau ngày nhận")
    if quantity <= 0:
        raise ValueError("Số lượng phải lớn hơn 0")
    result = unwrap_gateway_data(await client.get("/api/v1/availability", token, params={
        "organizationId": organization_id, "branchId": branch_id,
        "equipmentTypeId": equipment_type_id, "startAt": start.isoformat(),
        "endAt": end.isoformat(), "quantity": quantity,
    }))
    if not isinstance(result, dict) or not isinstance(result.get("available"), bool):
        raise GatewayError(502, "Backend trả dữ liệu availability không hợp lệ")
    return {
        "organizationId": organization_id, "branchId": branch_id,
        "equipmentTypeId": equipment_type_id, "startAt": start_at,
        "endAt": end_at, "requestedQuantity": quantity, **result,
    }
