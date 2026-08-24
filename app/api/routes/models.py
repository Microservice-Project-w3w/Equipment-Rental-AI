from fastapi import APIRouter
import os

router = APIRouter(tags=["Models"])

@router.get("/models")
async def get_models():
    return {"model": os.getenv("OLLAMA_MODEL", "viet-tutor-frog")}
