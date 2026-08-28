from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class LifecycleEvent:
    """所有生命周期事件都携带 request_id，供 SSE 按请求隔离。"""

    request_id: UUID


@dataclass(frozen=True)
class TurnStarted(LifecycleEvent):
    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    run_id: UUID
    started_at: datetime


@dataclass(frozen=True)
class ContextAssemblyStarted(LifecycleEvent):
    turn_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class ContextAssembled(LifecycleEvent):
    turn_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class ReasoningStarted(LifecycleEvent):
    turn_id: UUID
    run_id: UUID
    step_index: int


@dataclass(frozen=True)
class ReasoningCompleted(LifecycleEvent):
    turn_id: UUID
    run_id: UUID
    step_index: int
    action_type: str


@dataclass(frozen=True)
class CapabilityStarted(LifecycleEvent):
    turn_id: UUID
    run_id: UUID
    call_id: UUID
    capability: str


@dataclass(frozen=True)
class CapabilityCompleted(LifecycleEvent):
    turn_id: UUID
    run_id: UUID
    call_id: UUID
    capability: str
    status: str
    duration_ms: int


@dataclass(frozen=True)
class TurnCommitStarted(LifecycleEvent):
    turn_id: UUID
    thread_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class TurnCommitted(LifecycleEvent):
    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    run_id: UUID
    committed_at: datetime


@dataclass(frozen=True)
class TurnFailed(LifecycleEvent):
    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    run_id: UUID
    error: str


@dataclass(frozen=True)
class TurnCancelled(LifecycleEvent):
    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    run_id: UUID


ConversationLifecycleEvent = (
    TurnStarted | TurnCommitStarted | TurnCommitted | TurnFailed | TurnCancelled
)
AgentExecutionLifecycleEvent = (
    ContextAssemblyStarted
    | ContextAssembled
    | ReasoningStarted
    | ReasoningCompleted
    | CapabilityStarted
    | CapabilityCompleted
)
AnyLifecycleEvent = ConversationLifecycleEvent | AgentExecutionLifecycleEvent


def event_as_log_fields(event: LifecycleEvent) -> dict[str, Any]:
    return {
        "event_type": type(event).__name__,
        "request_id": str(event.request_id),
        **{
            key: (value.isoformat() if isinstance(value, datetime) else str(value))
            for key, value in vars(event).items()
            if key != "request_id"
        },
    }
