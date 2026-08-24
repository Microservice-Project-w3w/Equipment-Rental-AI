from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversationId: str | None = Field(default=None, max_length=100)


class SourceItem(BaseModel):
    service: str
    endpoint: str


class ChatResponse(BaseModel):
    conversationId: str
    answer: str
    data: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    sources: list[SourceItem] = Field(default_factory=list)
