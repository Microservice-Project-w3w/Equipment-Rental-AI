from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ChatRequest(BaseModel):
    message: str
    conversationId: Optional[str] = None

class SourceItem(BaseModel):
    service: str
    endpoint: str

class ChatResponse(BaseModel):
    conversationId: str
    answer: str
    data: List[Dict[str, Any]] = []
    actions: List[str] = []
    sources: List[SourceItem] = []
