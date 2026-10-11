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
    gateway_task = ApiGatewayClient(settings).check_health()
    if settings.chat_mode == "light":
        gateway_result, = await asyncio.gather(gateway_task, return_exceptions=True)
        ollama_result = {"status": "SKIPPED", "reason": "Chế độ light không dùng Ollama"}
    else:
        ollama_result, gateway_result = await asyncio.gather(
            OllamaClient(settings).check_health(), gateway_task, return_exceptions=True)

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
            ready = isinstance(result, dict) and result.get("status") in {"UP", "SKIPPED"}
            healthy = healthy and ready
            dependencies[name] = {"status": result["status"] if ready else "DEGRADED", "detail": result}

    return {
        "status": "UP" if healthy else "DEGRADED",
        "dependencies": dependencies,
    }
