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

# 需要兜底恢复的四类任务。
_RECOVERY_TASKS = (
    FINALIZE_TERMINAL_TURN,
    RECOMPUTE_ATHLETE_STATE,
    PROJECT_SEMANTIC_MEMORY,
    PROJECT_EPISODE,
)


@dataclass(frozen=True)
class RecoveryScanResult:
    """一次恢复扫描的统计（不可变数据类）。"""

    events_scanned: int  # 涉及的事件数（同一事件的多个任务按一个事件计）
    tasks_reenqueued: int  # 重新入队的任务数


class OutboxRecoveryScanner:
    """兜底恢复：扫描“已发布但迟迟没有消费回执”的事件，重新入队（防 Redis 丢任务）。"""

    def __init__(
        self,
        *,
        outbox: SqlAlchemyOutboxRepository,
        queue: QueuePublisher,
        clock: Clock,
        safety_window: timedelta = timedelta(minutes=10),
        batch_size: int = 100,
    ) -> None:
        self._outbox = outbox  # outbox 仓库：事件与发布状态的真相来源（PostgreSQL）
        self._queue = queue  # 队列发布端口
        self._clock = clock  # 时钟：统一取“当前时间”
        self._safety_window = safety_window  # 安全窗口：发布未满此时长不判丢失，避免与正常消费竞争
        self._batch_size = batch_size  # 每类任务单批最多恢复的事件数

    async def scan(self) -> RecoveryScanResult:
        """逐任务类型扫描缺回执的事件并重新入队；消费侧回执幂等，重复入队安全。"""
        now = self._clock.now()
        scanned_event_ids = set()
        reenqueued = 0
        for task_name in _RECOVERY_TASKS:
            # 找出发布时间早于 cutoff、且对应任务还没有终态消费回执的事件。
            events = await self._outbox.list_published_without_terminal_receipt(
                consumer_name=task_name,
                consumer_version=TASK_VERSION,
                event_types=event_types_for_task(task_name),
                cutoff=now - self._safety_window,
                limit=self._batch_size,
            )
            for event in events:
                # 从该事件的全部路由任务里挑出当前扫描的任务类型。
                task = next(
                    item
                    for item in route_event(event, enqueued_at=now)
                    if item.task_name == task_name
                )
                # 重新入队；即使原任务其实还在队列里，消费回执也会保证不重复执行。
                await self._queue.enqueue(task)
                scanned_event_ids.add(event.event_id)
                reenqueued += 1
        return RecoveryScanResult(
            events_scanned=len(scanned_event_ids),
            tasks_reenqueued=reenqueued,
        )