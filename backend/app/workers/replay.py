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
    """一次人工重放（replay）的结果（不可变数据类）。"""

    event_id: UUID  # 被重放的事件
    task_name: str  # 重放的任务名
    task_version: int  # 重放的任务契约版本


class WorkerTaskReplayer:
    """人工重放死信任务：重置消费回执并把任务重新入队。"""

    def __init__(
        self,
        *,
        outbox: SqlAlchemyOutboxRepository,
        receipts: SqlAlchemyConsumptionRepository,
        queue: QueuePublisher,
        clock: Clock,
    ) -> None:
        self._outbox = outbox  # outbox 仓库：按事件 ID 取原始事件
        self._receipts = receipts  # 消费回执仓库：重放前先重置状态
        self._queue = queue  # 队列发布端口
        self._clock = clock  # 时钟：统一取“当前时间”

    async def replay(
        self,
        *,
        event_id: UUID,
        consumer_name: str,
        consumer_version: int,
    ) -> ReplayResult:
        """重放指定任务的死信：三元组（事件 ID + 任务名 + 版本）必须与当前路由一致。"""
        event = await self._outbox.get(event_id=event_id)
        if event is None:
            # outbox 中不存在该事件：无法重放。
            raise NotFoundError("outbox_event_not_found")
        task = next(
            (
                item
                for item in route_event(event, enqueued_at=self._clock.now())
                if item.task_name == consumer_name and item.task_version == consumer_version
            ),
            None,
        )
        # 任务名 / 版本与该事件当前路由不一致：拒绝，防止重放到错误任务。
        if task is None or consumer_version != TASK_VERSION:
            raise ConflictError("worker_route_mismatch")
        # 重置该任务的回执状态，让这次投递可以重新消费。
        await self._receipts.replay(
            consumer_name=consumer_name,
            consumer_version=consumer_version,
            event_id=event_id,
        )
        # 重新入队；消费侧仍按回执流程幂等执行。
        await self._queue.enqueue(task)
        return ReplayResult(
            event_id=event_id,
            task_name=consumer_name,
            task_version=consumer_version,
        )
