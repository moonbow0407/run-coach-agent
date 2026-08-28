from collections.abc import Awaitable, Callable
from inspect import isawaitable

from app.agent.lifecycle.events import LifecycleEvent

LifecycleListener = Callable[[LifecycleEvent], Awaitable[None] | None]


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
        for listener in list(self._listeners):
            result = listener(event)
            if isawaitable(result):
                await result
