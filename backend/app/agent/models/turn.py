from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TurnStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Turn:
    id: UUID
    thread_id: UUID
    user_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID | None
    status: TurnStatus
    started_at: datetime
    committed_at: datetime | None
