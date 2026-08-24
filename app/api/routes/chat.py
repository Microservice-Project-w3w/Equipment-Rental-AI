from fastapi import APIRouter, Depends
from app.schemas.chat import ChatRequest, ChatResponse
from app.api.dependencies import get_token_header
from app.chatbot.orchestrator import ChatOrchestrator
import uuid

router = APIRouter(tags=["Chat"])
orchestrator = ChatOrchestrator()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, token: str = Depends(get_token_header)):
    conversation_id = request.conversationId or str(uuid.uuid4())
    
    result = await orchestrator.handle_message(
        message=request.message,
        token=token,
        conversation_id=conversation_id
    )
    
    return ChatResponse(**result)
