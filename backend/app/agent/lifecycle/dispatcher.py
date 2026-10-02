"""lifecycle dispatcher：进程内生命周期事件分发，把执行进展广播给监听器。

监听器用于 SSE 推送、日志等副作用；本模块只做进程内分发，不负责持久化。
"""

import logging
from collections.abc import Awaitable, Callable
from inspect import isawaitable

from app.agent.lifecycle.events import (
    LifecycleEvent,
    ResponseDelta,
    event_as_log_fields,
)

# 监听器：同步或 async 可调用对象，收到事件后执行副作用（如 SSE 推送）
LifecycleListener = Callable[[LifecycleEvent], Awaitable[None] | None]
logger = logging.getLogger(__name__)


class LifecycleDispatcher:
    """进程内生命周期事件总线。

    Phase 1 明确接受 DB COMMIT 成功后、publish 之前进程崩溃的窗口，
    不引入 Transactional Outbox。
    """

    def __init__(self) -> None:
        self._listeners: list[LifecycleListener] = []

    def subscribe(self, listener: LifecycleListener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: LifecycleListener) -> None:
        self._listeners.remove(listener)

    async def publish(self, event: LifecycleEvent) -> None:
        """发布关键执行事件，listener 失败会中止当前执行。"""
        _log_event(event)
        for listener in list(self._listeners):
            result = listener(event)
            # 兼容同步 / 异步监听器：只有返回 awaitable 才等待
            if isawaitable(result):
                await result

    async def publish_after_commit(self, event: LifecycleEvent) -> None:
        """发布已持久化终态事件，listener 失败不得改变业务结果。"""
        _log_event(event)
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if isawaitable(result):
                    await result
            except Exception:
                # 单个监听器失败只记日志：终态事件的副作用不允许影响业务结果
                logger.exception(
                    "lifecycle.listener.failed",
                    extra=event_as_log_fields(event),
                )


def _log_event(event: LifecycleEvent) -> None:
    """把事件写进结构化日志；ResponseDelta 高频且含用户正文，需单独脱敏。"""
    if isinstance(event, ResponseDelta):
        # 增量正文绝不进日志（与 Phase 5「日志不记 message content」同一原则）：
        # 只在 DEBUG 级别记录步序与片段长度，便于排查而不泄露内容。
        logger.debug(
            "ResponseDelta step=%s len=%s",
            event.step_index,
            len(event.delta),
            extra={"request_id": str(event.request_id)},
        )
        return
    logger.info(type(event).__name__, extra=event_as_log_fields(event))
