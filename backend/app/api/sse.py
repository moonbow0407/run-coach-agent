"""SSE 适配层：把进程内 Lifecycle 事件翻译成前端可读的 SSE 事件。

ChatService 与 AgentRuntime 只发布领域生命周期事件，不直接操作 HTTP；
本模块是“事件 → 传输格式（event: xxx + data: {...}）”的唯一映射点，
未来同一份事件还可以驱动日志、指标、评估等其它 Adapter。
"""

import json
from collections.abc import AsyncIterator

from app.agent.lifecycle.events import (
    CapabilityCompleted,
    CapabilityStarted,
    LifecycleEvent,
    ReasoningStarted,
    TurnCancelled,
    TurnCommitted,
    TurnFailed,
    TurnStarted,
)


def map_lifecycle_event(event: LifecycleEvent) -> tuple[str, dict[str, object]] | None:
    """Lifecycle 事件 → (SSE 事件名, 载荷)。

    返回 None 表示该事件不需要推给前端（如 ContextAssemblyStarted）。
    """
    if isinstance(event, TurnStarted):
        return "run.started", {
            "turn_id": str(event.turn_id),
            "run_id": str(event.run_id),
            "thread_id": str(event.thread_id),
        }
    if isinstance(event, ReasoningStarted):
        return "reasoning.started", {
            "turn_id": str(event.turn_id),
            "run_id": str(event.run_id),
            "step_index": event.step_index,
        }
    if isinstance(event, CapabilityStarted):
        return "capability.started", {
            "capability": event.capability,
            "call_id": str(event.call_id),
        }
    if isinstance(event, CapabilityCompleted):
        return "capability.completed", {
            "capability": event.capability,
            "call_id": str(event.call_id),
            "status": event.status,
            "duration_ms": event.duration_ms,
        }
    if isinstance(event, TurnCommitted):
        return "run.completed", {
            "turn_id": str(event.turn_id),
            "run_id": str(event.run_id),
            "message_id": str(event.assistant_message_id),
        }
    if isinstance(event, TurnFailed):
        return "run.failed", {"turn_id": str(event.turn_id), "error": event.error}
    if isinstance(event, TurnCancelled):
        return "run.cancelled", {"turn_id": str(event.turn_id)}
    return None


def format_sse(event_name: str, payload: dict[str, object]) -> str:
    """按 SSE 协议格式化一条事件消息。"""
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def iter_sse(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    async for chunk in chunks:
        yield chunk
