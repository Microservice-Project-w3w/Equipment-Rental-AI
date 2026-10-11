from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversationId: str | None = Field(default=None, max_length=100)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Vui lòng nhập câu hỏi, không chỉ khoảng trắng.")
        return value

    @field_validator("conversationId")
    @classmethod
    def validate_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Mã hội thoại không hợp lệ.")
        return value


class SourceItem(BaseModel):
    service: str
    endpoint: str
    kind: Literal["API", "DATABASE_FALLBACK"] = "API"
    readAt: str | None = None


class ChatResponse(BaseModel):
    conversationId: str
    answer: str
    data: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    sources: list[SourceItem] = Field(default_factory=list)
