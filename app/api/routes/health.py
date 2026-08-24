import asyncio
from typing import Any

from fastapi import APIRouter

from app.clients.api_gateway_client import ApiGatewayClient
from app.clients.ollama_client import OllamaClient
from app.core.config import get_settings


router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "equipment-rental-ai"}


@router.get("/health/dependencies")
async def dependencies_health() -> dict[str, Any]:
    ollama_result, gateway_result = await asyncio.gather(
        OllamaClient(settings).check_health(),
        ApiGatewayClient(settings).check_health(),
        return_exceptions=True,
    )

    dependencies: dict[str, Any] = {}
    healthy = True
    for name, result in (
        ("ollama", ollama_result),
        ("apiGateway", gateway_result),
    ):
        if isinstance(result, Exception):
            healthy = False
            dependencies[name] = {"status": "DOWN", "detail": str(result)}
        else:
            dependencies[name] = {"status": "UP", "detail": result}

    return {
        "status": "UP" if healthy else "DEGRADED",
        "dependencies": dependencies,
    }
