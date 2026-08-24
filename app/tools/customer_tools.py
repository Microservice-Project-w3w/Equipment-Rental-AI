from typing import Any

from app.clients.api_gateway_client import ApiGatewayClient
from app.tools.common import unwrap_gateway_data


async def get_customer_info(
    client: ApiGatewayClient,
    token: str,
    organization_id: int,
    customer_id: int,
) -> dict[str, Any]:
    endpoint = f"/api/v1/organizations/{organization_id}/customers/{customer_id}"
    response = await client.get(endpoint, token)
    return unwrap_gateway_data(response)
