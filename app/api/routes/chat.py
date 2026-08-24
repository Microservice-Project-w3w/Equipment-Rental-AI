import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_access_token
from app.chatbot.orchestrator import ChatOrchestrator
from app.clients.api_gateway_client import GatewayError
from app.clients.ollama_client import OllamaError
from app.schemas.chat import ChatRequest, ChatResponse


router = APIRouter(tags=["Chat"])
orchestrator = ChatOrchestrator()


def _gateway_http_status(error: GatewayError) -> int:
    if error.status_code in (401, 403):
        return error.status_code
    if error.status_code == 503:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_502_BAD_GATEWAY


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    token: Annotated[str, Depends(get_access_token)],
) -> ChatResponse:
    conversation_id = request.conversationId or str(uuid.uuid4())
    try:
        result = await orchestrator.handle_message(
            message=request.message,
            token=token,
            conversation_id=conversation_id,
        )
    except GatewayError as exc:
        raise HTTPException(
            status_code=_gateway_http_status(exc),
            detail=exc.detail,
        ) from exc
    except OllamaError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return ChatResponse(**result)


@router.delete("/chat/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation(
    conversation_id: str,
    token: Annotated[str, Depends(get_access_token)],
) -> None:
    try:
        await orchestrator.clear_conversation(token, conversation_id)
    except GatewayError as exc:
        raise HTTPException(
            status_code=_gateway_http_status(exc),
            detail=exc.detail,
        ) from exc
