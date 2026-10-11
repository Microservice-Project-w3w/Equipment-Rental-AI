from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes.health import dependencies_health
from app.clients.ollama_client import OllamaClient
from app.core.config import Settings

@pytest.mark.asyncio
async def test_missing_configured_model_is_not_reported_as_ready():
    client = OllamaClient(Settings(ollama_model="demo-model"))
    with patch.object(client, "list_models", AsyncMock(return_value=[{"name": "other:latest"}])):
        result = await client.check_health()
    assert result["status"] == "DEGRADED"
    assert result["modelAvailable"] is False

@pytest.mark.asyncio
async def test_dependency_status_propagates_model_not_ready():
    with patch("app.api.routes.health.OllamaClient.check_health", AsyncMock(return_value={"status": "DEGRADED", "modelAvailable": False})), patch("app.api.routes.health.ApiGatewayClient.check_health", AsyncMock(return_value={"status": "UP"})):
        result = await dependencies_health()
    assert result["status"] == "DEGRADED"
    assert result["dependencies"]["ollama"]["status"] == "DEGRADED"
