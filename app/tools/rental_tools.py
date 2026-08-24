from app.clients.api_gateway_client import ApiGatewayClient

async def get_pending_quotations(client: ApiGatewayClient, token: str):
    """
    Gọi qua API Gateway để lấy danh sách báo giá chờ duyệt.
    """
    endpoint = "/rental-service/api/v1/quotations?status=pending"
    return await client.get(endpoint, token)
