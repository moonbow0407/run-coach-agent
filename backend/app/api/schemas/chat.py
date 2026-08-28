from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: UUID | None = None
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    thread_id: UUID
    turn_id: UUID
    message_id: UUID
    content: str


class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: str


class ThreadMessagesResponse(BaseModel):
    thread_id: UUID
    messages: list[MessageResponse]
