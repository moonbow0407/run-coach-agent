from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AgentTurnCommand:
    user_id: UUID
    thread_id: UUID
    turn_id: UUID
    run_id: UUID
    request_id: UUID
    timestamp: datetime
    current_input: str
