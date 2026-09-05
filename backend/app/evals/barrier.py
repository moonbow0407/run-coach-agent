"""Durable 一致性屏障：复用正式 Publisher / Consumer / Handler 排空 Outbox。

Eval 不启动真实 Redis：Queue 为进程内收集实现，Publisher 与 Consumer 及
四个正式 Handler 全部复用生产实现。屏障持续排空新产生的 Outbox，直到没有
新 claim；任何任务死信、事件隔离或超出有界排空次数都抛 EvalBarrierError，
使对应 Trial 进入 ERROR（环境失败，不属于行为 FAIL）。
"""

from dataclasses import dataclass, field
from datetime import timedelta

from app.bootstrap import AppContainer
from app.evals.errors import EvalBarrierError
from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.workers.consumer import ConsumerRunner
from app.workers.errors import WorkerRetryRequested
from app.workers.handlers import DurableTaskHandlers
from app.workers.publisher import OutboxPublisher

MAX_DRAIN_ROUNDS = 50  # 有界排空：超过说明队列持续产生新任务，属于异常
MAX_TASK_RETRIES = 20  # 单任务最大重投次数（瞬时失败在进程内立即重投）


class CollectingQueue:
    """arq 队列替身：把任务收进内存列表，不真正投递 Redis。"""

    def __init__(self) -> None:
        self.tasks: list = []

    async def enqueue(self, task, *, defer_by: timedelta | None = None) -> None:
        self.tasks.append(task)


@dataclass
class DrainStats:
    """一次排空的统计：任务数 / 重投次数 / 死信数 / 隔离数。"""

    consumed: int = 0
    retried: int = 0
    dead_lettered: int = 0
    quarantined: int = 0
    details: list[str] = field(default_factory=list)


async def drain_durable_tasks(container: AppContainer) -> DrainStats:
    """把容器 Outbox 积压任务全部经正式发布/消费链路消化，直到没有新 claim。"""
    queue = CollectingQueue()
    outbox = SqlAlchemyOutboxRepository(container.sessions)
    receipts = SqlAlchemyConsumptionRepository(container.sessions)
    publisher = OutboxPublisher(
        repository=outbox,
        queue=queue,
        clock=container.clock,
        worker_id="eval-publisher",
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
        worker_id="eval-consumer",
    )
    stats = DrainStats()
    consumed = 0  # 已消费到的队列游标
    for _round in range(MAX_DRAIN_ROUNDS):
        published = await publisher.publish_batch()
        stats.quarantined += published.quarantined
        if published.quarantined > 0:
            # 事件隔离属于环境失败：不得假装排空成功后继续评分。
            stats.details.append(f"outbox_quarantined:{published.quarantined}")
            raise EvalBarrierError(_message(stats))
        # 逐条消费本轮新增任务；瞬时失败（重试请求）立即重投队尾。
        while consumed < len(queue.tasks):
            task = queue.tasks[consumed]
            consumed += 1
            stats.consumed += 1
            try:
                result = await runner.consume(task)
            except WorkerRetryRequested:
                stats.retried += 1
                if stats.retried > MAX_TASK_RETRIES:
                    stats.details.append("retry_bound_exceeded")
                    raise EvalBarrierError(_message(stats))
                queue.tasks.append(task)  # 延迟重投在进程内退化为立即重投
                continue
            # 死信 / 已死信：投影未完成，必须 ERROR，不能继续 grader。
            if result.status in {"dead_lettered", "already_dead_lettered"}:
                stats.dead_lettered += 1
                stats.details.append(f"task_{result.status}:{task.task_name}")
                raise EvalBarrierError(_message(stats))
        if published.claimed == 0 and consumed >= len(queue.tasks):
            return stats  # 本轮无新认领且队列已排干：一致性屏障达成
    stats.details.append("drain_rounds_exceeded")
    raise EvalBarrierError(_message(stats))


def _message(stats: DrainStats) -> str:
    """把排空统计归并为简短错误说明（不含基础设施敏感信息）。"""
    return f"durable_barrier_failed({','.join(stats.details) or 'unknown'})"
