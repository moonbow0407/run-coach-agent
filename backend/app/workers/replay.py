"""显式重放 dead-letter task；只接受原 event 的完整 route 三元组。"""

from dataclasses import dataclass
from uuid import UUID

from app.common.clock import Clock
from app.common.errors import ConflictError, NotFoundError
from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.workers.contracts import TASK_VERSION
from app.workers.ports import QueuePublisher
from app.workers.routing import route_event


@dataclass(frozen=True)
class ReplayResult:
    event_id: UUID
    task_name: str
    task_version: int


class WorkerTaskReplayer:
    def __init__(
        self,
        *,
        outbox: SqlAlchemyOutboxRepository,
        receipts: SqlAlchemyConsumptionRepository,
        queue: QueuePublisher,
        clock: Clock,
    ) -> None:
        self._outbox = outbox
        self._receipts = receipts
        self._queue = queue
        self._clock = clock

    async def replay(
        self,
        *,
        event_id: UUID,
        consumer_name: str,
        consumer_version: int,
    ) -> ReplayResult:
        event = await self._outbox.get(event_id=event_id)
        if event is None:
            raise NotFoundError("outbox_event_not_found")
        task = next(
            (
                item
                for item in route_event(event, enqueued_at=self._clock.now())
                if item.task_name == consumer_name and item.task_version == consumer_version
            ),
            None,
        )
        if task is None or consumer_version != TASK_VERSION:
            raise ConflictError("worker_route_mismatch")
        await self._receipts.replay(
            consumer_name=consumer_name,
            consumer_version=consumer_version,
            event_id=event_id,
        )
        await self._queue.enqueue(task)
        return ReplayResult(
            event_id=event_id,
            task_name=consumer_name,
            task_version=consumer_version,
        )
