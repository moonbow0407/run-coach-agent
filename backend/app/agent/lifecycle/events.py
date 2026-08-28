"""生命周期事件：系统各阶段进展的统一表达。

同一事件只有一个 Publisher Owner（AgentRuntime / ChatService）；
所有事件携带 request_id，供 SSE 按请求隔离。Phase 2 起 Tool 执行
事件使用 ToolStarted / ToolCompleted，不新增 ToolDiscovered 事件
（Discovery 信息以 search_tools 的 ToolCall / Observation Trace
为唯一详细记录）。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class LifecycleEvent:
    """所有生命周期事件都携带 request_id，供 SSE 按请求隔离。"""

    request_id: UUID
    trace_id: UUID


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
class ToolStarted(LifecycleEvent):
    """一次工具调用开始。call_id 是内部 Trace UUID（与模型协议 ID 分离）。"""

    turn_id: UUID
    run_id: UUID
    call_id: UUID
    tool: str


@dataclass(frozen=True)
class ToolCompleted(LifecycleEvent):
    """一次工具调用结束（成功或可恢复错误 Observation 都算完成）。"""

    turn_id: UUID
    run_id: UUID
    call_id: UUID
    tool: str
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
    | ToolStarted
    | ToolCompleted
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
