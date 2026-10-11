from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Any

from app.clients.api_gateway_client import ApiGatewayClient, GatewayError
from app.tools.inventory_tools import require_list


async def get_contract_values(
    client: ApiGatewayClient, token: str, organization_id: int,
    branch_ids: tuple[int, ...], *, contract_id: int | None = None,
) -> dict[str, Any]:
    responses = await asyncio.gather(*[
        client.get("/api/v1/rental-contracts", token, params={
            "organizationId": organization_id, "branchId": branch,
        }) for branch in branch_ids
    ])
    contracts = {}
    for response in responses:
        for contract in require_list(response):
            if contract.get("organizationId") != organization_id or contract.get("branchId") not in branch_ids:
                raise GatewayError(502, "Rental trả hợp đồng ngoài phạm vi yêu cầu")
            if contract_id is None or contract["id"] == contract_id:
                contracts[contract["id"]] = contract
    live_contracts = [c for c in contracts.values() if c.get("status") in {"SIGNED", "ACTIVE", "EXTENDED"}]
    try:
        total = sum((Decimal(str(c["totalAmount"])) for c in live_contracts), Decimal(0))
        if not total.is_finite():
            raise InvalidOperation()
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise GatewayError(502, "Rental trả giá trị hợp đồng không hợp lệ") from exc
    fields = ("id", "contractCode", "branchId", "customerId", "rentalOrderId",
              "status", "startAt", "endAt", "totalAmount")
    return {
        "contracts": [{field: c.get(field) for field in fields} for c in list(contracts.values())[:50]],
        "totalContracts": len(contracts), "contractListTruncated": len(contracts) > 50,
        "activeContractValue": str(total), "currency": "VND",
        "paymentsAvailable": False, "paidAmount": None, "outstandingAmount": None,
        "note": "Chỉ có giá trị hợp đồng; không phải doanh thu đã thu. Chưa có API hóa đơn/thanh toán/công nợ/thu cọc, không thể kết luận đã trả tiền hoặc còn nợ.",
    }
