"""生命周期事件：ChatService 与 AgentRuntime 在关键节点发布的领域事件。

事件本身不承载业务逻辑，只是“某事已发生”的通知；消费方（SSE 适配、
日志、未来的 Worker）各自决定如何反应。事件分两类：

    Conversation 事件   Turn 级别：开始 / 提交 / 失败 / 取消（由 ChatService 发布）
    Agent 执行事件      Run 级别：上下文装配 / 推理 / 能力调用（由 AgentRuntime 发布）

每个事件都携带 request_id / trace_id，用于把一次请求的完整执行链串联起来。
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
    """把事件展开成结构化日志字段（datetime 转 ISO 字符串），便于按 run 串联日志。"""
    return {
        "event_type": type(event).__name__,
        "request_id": str(event.request_id),
        **{
            key: (value.isoformat() if isinstance(value, datetime) else str(value))
            for key, value in vars(event).items()
            if key != "request_id"
        },
    }
