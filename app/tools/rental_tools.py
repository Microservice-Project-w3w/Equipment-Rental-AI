from typing import Any

from app.clients.api_gateway_client import ApiGatewayClient
from app.tools.common import unwrap_gateway_data


PENDING_APPROVAL_STATUSES = {"PENDING_APPROVAL", "SENT"}


async def get_pending_quotations(
    client: ApiGatewayClient,
    token: str,
    organization_id: int,
    branch_id: int,
) -> list[dict[str, Any]]:
    response = await client.get(
        "/api/v1/quotations",
        token,
        params={
            "organizationId": organization_id,
            "branchId": branch_id,
        },
    )
    quotations = unwrap_gateway_data(response)
    if not isinstance(quotations, list):
        return []

    # Rental hiện chuyển báo giá DRAFT thành SENT khi gửi quản lý.
    # Giữ thêm PENDING_APPROVAL để tương thích khi backend dùng trạng thái này.
    return [
        quotation
        for quotation in quotations
        if str(quotation.get("status", "")).upper() in PENDING_APPROVAL_STATUSES
    ]
