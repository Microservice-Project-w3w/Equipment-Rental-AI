import httpx
import pytest

from app.clients.api_gateway_client import ApiGatewayClient
from app.core.config import Settings


def test_rejects_internal_and_service_prefixed_paths():
    with pytest.raises(ValueError):
        ApiGatewayClient._validate_endpoint("/internal/inventory/equipment")

    with pytest.raises(ValueError):
        ApiGatewayClient._validate_endpoint(
            "/rental-service/api/v1/quotations"
        )


@pytest.mark.asyncio
async def test_forwards_jwt_and_query_to_gateway():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer valid-token"
        assert request.url.path == "/api/v1/quotations"
        assert request.url.params["organizationId"] == "1"
        assert request.url.params["branchId"] == "2"
        return httpx.Response(200, json={"success": True, "data": []})

    settings = Settings(
        _env_file=None,
        ollama_model="test-model",
        api_gateway_base_url="http://gateway.test",
    )
    client = ApiGatewayClient(settings, httpx.MockTransport(handler))

    result = await client.get(
        "/api/v1/quotations",
        "valid-token",
        params={"organizationId": 1, "branchId": 2},
    )

    assert result == {"success": True, "data": []}
