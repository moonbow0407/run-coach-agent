from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Thread:
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
