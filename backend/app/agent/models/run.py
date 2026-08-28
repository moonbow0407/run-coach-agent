from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStepKind(StrEnum):
    REASONING = "reasoning"
    CAPABILITY_CALL = "capability_call"
    OBSERVATION = "observation"
    FINAL = "final"


@dataclass(frozen=True)
class AgentRun:
    id: UUID
    turn_id: UUID
    user_id: UUID
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RunStep:
    """持久化 Execution Trace。不能被当作 AgentRuntime 的工作状态。"""

    id: UUID
    run_id: UUID
    index: int
    kind: RunStepKind
    call_id: UUID | None
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
