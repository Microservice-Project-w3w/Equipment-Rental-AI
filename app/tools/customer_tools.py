from app.clients.api_gateway_client import ApiGatewayClient

async def get_customer_info(client: ApiGatewayClient, token: str, customer_id: str):
    """
    Gọi qua API Gateway để lấy thông tin khách hàng.
    """
    endpoint = f"/customer-service/api/v1/customers/{customer_id}"
    return await client.get(endpoint, token)
