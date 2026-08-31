"""回归测试用 durable pipeline 驱动；可靠性 acceptance 仍使用真实 Redis。"""

from datetime import timedelta

from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.workers.consumer import ConsumeResult, ConsumerRunner
from app.workers.contracts import WorkerTaskEnvelope
from app.workers.handlers import DurableTaskHandlers
from app.workers.publisher import OutboxPublisher


class CollectingQueue:
    def __init__(self) -> None:
        self.tasks: list[WorkerTaskEnvelope] = []

    async def enqueue(
        self,
        task: WorkerTaskEnvelope,
        *,
        defer_by: timedelta | None = None,
    ) -> None:
        self.tasks.append(task)


async def drain_durable_tasks(app) -> tuple[ConsumeResult, ...]:
    container = app.state.container
    queue = CollectingQueue()
    outbox = SqlAlchemyOutboxRepository(container.sessions)
    receipts = SqlAlchemyConsumptionRepository(container.sessions)
    publisher = OutboxPublisher(
        repository=outbox,
        queue=queue,
        clock=container.clock,
        worker_id="test-publisher",
    )
    handlers = DurableTaskHandlers(
        terminal_turn_finalization=container.terminal_turn_finalization_service,
        athlete_recompute=container.athlete_recompute_service,
        semantic_projection=container.semantic_memory_projection_service,
        episode_projection=container.episode_projection_service,
        memory_projector_version=container.settings.memory_projector_version,
    )
    runner = ConsumerRunner(
        receipts=receipts,
        handlers=handlers.mapping(),
        clock=container.clock,
        worker_id="test-consumer",
    )
    results: list[ConsumeResult] = []
    consumed = 0
    while True:
        published = await publisher.publish_batch()
        while consumed < len(queue.tasks):
            results.append(await runner.consume(queue.tasks[consumed]))
            consumed += 1
        if published.claimed == 0:
            break
    return tuple(results)
