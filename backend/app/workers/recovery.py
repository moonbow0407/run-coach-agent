"""从 PostgreSQL 审计状态重建 Redis 中可能丢失的 durable tasks。"""

from dataclasses import dataclass
from datetime import timedelta

from app.common.clock import Clock
from app.infrastructure.outbox.repository import SqlAlchemyOutboxRepository
from app.workers.contracts import TASK_VERSION
from app.workers.ports import QueuePublisher
from app.workers.routing import (
    FINALIZE_TERMINAL_TURN,
    PROJECT_EPISODE,
    PROJECT_SEMANTIC_MEMORY,
    RECOMPUTE_ATHLETE_STATE,
    event_types_for_task,
    route_event,
)

_RECOVERY_TASKS = (
    FINALIZE_TERMINAL_TURN,
    RECOMPUTE_ATHLETE_STATE,
    PROJECT_SEMANTIC_MEMORY,
    PROJECT_EPISODE,
)


@dataclass(frozen=True)
class RecoveryScanResult:
    events_scanned: int
    tasks_reenqueued: int


class OutboxRecoveryScanner:
    def __init__(
        self,
        *,
        outbox: SqlAlchemyOutboxRepository,
        queue: QueuePublisher,
        clock: Clock,
        safety_window: timedelta = timedelta(minutes=10),
        batch_size: int = 100,
    ) -> None:
        self._outbox = outbox
        self._queue = queue
        self._clock = clock
        self._safety_window = safety_window
        self._batch_size = batch_size

    async def scan(self) -> RecoveryScanResult:
        now = self._clock.now()
        scanned_event_ids = set()
        reenqueued = 0
        for task_name in _RECOVERY_TASKS:
            events = await self._outbox.list_published_without_terminal_receipt(
                consumer_name=task_name,
                consumer_version=TASK_VERSION,
                event_types=event_types_for_task(task_name),
                cutoff=now - self._safety_window,
                limit=self._batch_size,
            )
            for event in events:
                task = next(
                    item
                    for item in route_event(event, enqueued_at=now)
                    if item.task_name == task_name
                )
                await self._queue.enqueue(task)
                scanned_event_ids.add(event.event_id)
                reenqueued += 1
        return RecoveryScanResult(
            events_scanned=len(scanned_event_ids),
            tasks_reenqueued=reenqueued,
        )