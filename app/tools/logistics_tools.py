from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.tools.inventory_tools import require_list


async def get_rental_handover_plan(
    client: ApiGatewayClient, token: str, organization_id: int,
    branch_ids: tuple[int, ...], *, from_date: str | None = None,
    to_date: str | None = None, order_id: int | None = None,
) -> dict[str, Any]:
    try:
        start = date.fromisoformat(from_date) if from_date else None
        end = date.fromisoformat(to_date) if to_date else None
    except ValueError as exc:
        raise ValueError("Khoảng ngày phải theo định dạng YYYY-MM-DD") from exc
    if start and end and end < start:
        raise ValueError("Ngày kết thúc phải từ ngày bắt đầu trở đi")
    paths = ("/api/v1/rental-orders", "/api/v1/quotations", "/api/v1/rental-requests")
    responses = await asyncio.gather(*[
        client.get(path, token, params={"organizationId": organization_id, "branchId": branch})
        for path in paths for branch in branch_ids
    ])
    groups = {}
    for index, path in enumerate(paths):
        records = {}
        for response in responses[index * len(branch_ids):(index + 1) * len(branch_ids)]:
            for row in require_list(response):
                if row.get("organizationId") != organization_id or row.get("branchId") not in branch_ids:
                    raise GatewayError(502, "Rental trả dữ liệu ngoài phạm vi yêu cầu")
                records[row["id"]] = row
        groups[path] = records
    orders, quotations, requests = (groups[path] for path in paths)
    events = []
    for order in orders.values():
        if order.get("status") in {"CANCELLED", "EXPIRED"} or (order_id and order["id"] != order_id):
            continue
        quotation = quotations.get(order.get("quotationId"), {})
        request = requests.get(quotation.get("rentalRequestId"), {})
        for event_type, field in (("EXPECTED_HANDOVER", "startAt"), ("EXPECTED_RETURN", "endAt")):
            scheduled_at = order.get(field)
            if not scheduled_at:
                continue
            try:
                scheduled_date = date.fromisoformat(scheduled_at[:10])
            except ValueError as exc:
                raise GatewayError(502, "Rental trả ngày thuê không hợp lệ") from exc
            if (start and scheduled_date < start) or (end and scheduled_date > end):
                continue
            events.append({
                "orderId": order["id"], "orderCode": order.get("orderCode"),
                "branchId": order["branchId"], "customerId": order.get("customerId"),
                "orderStatus": order.get("status"), "eventType": event_type,
                "scheduledAt": scheduled_at,
                "deliveryAddress": request.get("deliveryAddress") if event_type == "EXPECTED_HANDOVER" else None,
            })
    events.sort(key=lambda e: (e["scheduledAt"], e["orderId"]))
    return {
        "events": events[:50], "totalEvents": len(events), "eventListTruncated": len(events) > 50,
        "actualDeliveryTrackingAvailable": False,
        "note": "Đây là kế hoạch dự kiến theo ngày bắt đầu/kết thúc đơn thuê, không phải phiếu giao nhận hay bằng chứng đã giao/đã nhận. Đơn PENDING/RESERVED chưa xác nhận; chưa có API vận chuyển, người giao hay biên bản nhận trả.",
    }
