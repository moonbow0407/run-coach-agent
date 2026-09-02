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
    trace_id: UUID  # 追踪 ID，用于关联日志与执行轨迹


@dataclass(frozen=True)
class TurnStarted(LifecycleEvent):
    """一轮对话开始：事务 A 已提交，Turn / 用户消息 / AgentRun 均落库。"""

    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    run_id: UUID
    started_at: datetime  # Turn 开始时间


@dataclass(frozen=True)
class ContextAssemblyStarted(LifecycleEvent):
    """开始装配本轮推理上下文。"""

    turn_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class ContextAssembled(LifecycleEvent):
    """上下文装配完成，即将进入推理循环。"""

    turn_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class ReasoningStarted(LifecycleEvent):
    """一轮推理开始。"""

    turn_id: UUID
    run_id: UUID
    step_index: int  # 本步在 Run 内的序号，从 0 开始


@dataclass(frozen=True)
class ReasoningCompleted(LifecycleEvent):
    """一轮推理结束，模型已给出 Action。"""

    turn_id: UUID
    run_id: UUID
    step_index: int
    action_type: str  # Action 类型（tool_call 或 final）


@dataclass(frozen=True)
class ToolStarted(LifecycleEvent):
    """一次工具调用开始。call_id 是内部 Trace UUID（与模型协议 ID 分离）。"""

    turn_id: UUID
    run_id: UUID
    call_id: UUID
    tool: str  # 被调用的工具名


@dataclass(frozen=True)
class ToolCompleted(LifecycleEvent):
    """一次工具调用结束（成功或可恢复错误 Observation 都算完成）。"""

    turn_id: UUID
    run_id: UUID
    call_id: UUID
    tool: str
    status: str  # success 或 error
    duration_ms: int  # 工具执行耗时（毫秒）


@dataclass(frozen=True)
class TurnCommitStarted(LifecycleEvent):
    """开始提交一轮成功对话（事务 B 开始）。"""

    turn_id: UUID
    thread_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class TurnCommitted(LifecycleEvent):
    """对话已成功提交：助手消息落库，Turn 置为 committed。"""

    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    user_message_id: UUID  # 本轮用户消息
    assistant_message_id: UUID  # 本轮助手回复
    run_id: UUID
    committed_at: datetime  # 提交时间


@dataclass(frozen=True)
class TurnFailed(LifecycleEvent):
    """Turn 以失败终态结束。"""

    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    run_id: UUID
    error: str  # 归一化后的失败说明


@dataclass(frozen=True)
class TurnCancelled(LifecycleEvent):
    """Turn 被取消（客户端断开或显式取消），属正常语义而非错误。"""

    turn_id: UUID
    thread_id: UUID
    user_id: UUID
    run_id: UUID


# 会话生命周期事件：由 ChatService 在事务边界发布
ConversationLifecycleEvent = (
    TurnStarted | TurnCommitStarted | TurnCommitted | TurnFailed | TurnCancelled
)
# Agent 执行过程事件：由 AgentRuntime 在推理循环内发布
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
    """把事件摊平成结构化日志字段；datetime 转 ISO 字符串便于检索。"""
    return {
        "event_type": type(event).__name__,
        "request_id": str(event.request_id),
        **{
            key: (value.isoformat() if isinstance(value, datetime) else str(value))
            for key, value in vars(event).items()
            if key != "request_id"
        },
    }
