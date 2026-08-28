import logging
from collections.abc import Awaitable, Callable
from inspect import isawaitable

from app.agent.lifecycle.events import LifecycleEvent, event_as_log_fields

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
        logger.info(type(event).__name__, extra=event_as_log_fields(event))
        for listener in list(self._listeners):
            result = listener(event)
            if isawaitable(result):
                await result

    async def publish_after_commit(self, event: LifecycleEvent) -> None:
        """发布已持久化终态事件，listener 失败不得改变业务结果。"""
        logger.info(type(event).__name__, extra=event_as_log_fields(event))
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "lifecycle.listener.failed",
                    extra=event_as_log_fields(event),
                )
