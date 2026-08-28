from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    """Canonical Conversation 消息。只保存 user / assistant，不保存工具调用。"""

    id: UUID
    thread_id: UUID
    turn_id: UUID
    role: MessageRole
    content: str
    created_at: datetime
