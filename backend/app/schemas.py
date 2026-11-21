"""Pydantic models for the public API contract."""

from typing import Any, Literal
from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    session_id: str
    message: str
    system_prompt: str | None = None

    @field_validator("message", mode="before")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        if len(value) > 4000:
            raise ValueError("message must contain at most 4000 characters")
        return value

    @field_validator("session_id", mode="before")
    @classmethod
    def session_id_must_not_be_blank(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError("session_id must contain 1–128 characters")
        return value


class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
