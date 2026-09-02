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
    """arq 队列替身：把任务收进内存列表，不真正投递 Redis。"""

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
    """把 app 内 outbox 积压任务全部经真实 publisher/consumer 链路消化，返回逐条消费结果。"""
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
        # 每轮：publisher 从 outbox 认领一批任务入队，consumer 逐条消费并写 receipt
        published = await publisher.publish_batch()
        while consumed < len(queue.tasks):
            results.append(await runner.consume(queue.tasks[consumed]))
            consumed += 1
        if published.claimed == 0:
            break  # 本轮无新认领，说明 outbox 已全部排干
    return tuple(results)
