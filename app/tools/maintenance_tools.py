from typing import Any

from app.clients.api_gateway_client import ApiGatewayClient
from app.tools.inventory_tools import get_inventory_stock


async def get_maintenance_equipment(
    client: ApiGatewayClient, token: str, organization_id: int,
    branch_ids: tuple[int, ...], *, keyword: str = "",
    include_warehouses: bool = False,
) -> dict[str, Any]:
    result = await get_inventory_stock(
        client, token, organization_id, branch_ids,
        keyword=keyword, maintenance_only=True,
        include_warehouses=include_warehouses,
    )
    result.update({
        "maintenanceScheduleAvailable": False,
        "maintenanceTicketsAvailable": False,
        "note": "Chỉ tra cứu thiết bị có trạng thái MAINTENANCE, DAMAGED hoặc INSPECTION trong Inventory. Chưa có API lịch bảo trì, phiếu sửa chữa, kỹ thuật viên hoặc chi phí bảo trì.",
    })
    return result
