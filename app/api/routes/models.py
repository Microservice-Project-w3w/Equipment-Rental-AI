from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.clients.ollama_client import OllamaClient, OllamaError
from app.core.config import get_settings


router = APIRouter(tags=["Models"])
settings = get_settings()


@router.get("/models")
async def get_models() -> dict[str, Any]:
    client = OllamaClient(settings)
    try:
        models = await client.list_models()
    except OllamaError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    names = [model.get("name") for model in models if model.get("name")]
    return {
        "configuredModel": settings.ollama_model,
        "modelAvailable": client.model_is_available(
            settings.ollama_model,
            names,
        ),
        "installedModels": names,
    }
