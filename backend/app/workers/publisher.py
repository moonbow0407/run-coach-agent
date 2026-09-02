"""Outbox Publisher：数据库 claim 与 Redis enqueue 之间不持有事务。"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter

from app.common.clock import Clock
from app.common.errors import DomainError
from app.infrastructure.outbox.repository import SqlAlchemyOutboxRepository
from app.workers.ports import QueuePublisher
from app.workers.retry import retry_delay
from app.workers.routing import route_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishBatchResult:
    """一批发布的统计结果（不可变数据类）。"""

    claimed: int  # 本批抢占到的待发布事件数
    published: int  # 成功投递到队列的事件数
    rescheduled: int  # 投递失败、按退避重排的事件数
    quarantined: int  # 数据损坏或不支持而隔离（quarantine）的事件数


class OutboxPublisher:
    """outbox（本地消息表）发布器：轮询业务事务落库的事件，投递到 arq 队列。"""

    def __init__(
        self,
        *,
        repository: SqlAlchemyOutboxRepository,
        queue: QueuePublisher,
        clock: Clock,
        worker_id: str,
        claim_lease: timedelta = timedelta(minutes=2),
        batch_size: int = 100,
    ) -> None:
        self._repository = repository  # outbox 仓库：待发布事件的存取
        self._queue = queue  # 队列发布端口（不依赖具体队列实现）
        self._clock = clock  # 时钟：统一取“当前时间”，便于测试注入
        self._worker_id = worker_id  # 本 Worker 标识：写入 claim，防多实例重复发布
        self._claim_lease = claim_lease  # claim 租约：发布中断后事件不会立刻被重新抢占
        self._batch_size = batch_size  # 单批最多处理的事件数

    async def publish_batch(self) -> PublishBatchResult:
        """处理一批待发布事件：逐条投递；投递失败按退避重排，坏数据隔离。"""
        # 抢占一批 pending 事件（带租约）：多实例部署下同一事件同一时刻只被一个实例发布。
        claimed = await self._repository.claim_pending(
            worker_id=self._worker_id,
            now=self._clock.now(),
            lease=self._claim_lease,
            limit=self._batch_size,
        )
        published = 0
        rescheduled = 0
        quarantined = 0
        for item in claimed:
            started = perf_counter()
            # 事件 JSON 损坏无法解码：隔离（quarantine）并告警，避免阻塞后续事件。
            if item.decode_error is not None or item.event is None:
                await self._repository.quarantine(
                    event_id=item.event_id,
                    worker_id=self._worker_id,
                    quarantined_at=self._clock.now(),
                    error_code=item.decode_error or "malformed_outbox_event",
                )
                quarantined += 1
                logger.error(
                    "outbox.event.quarantined",
                    extra={
                        "event_id": str(item.event_id),
                        "event_type": item.event_type,
                        "schema_version": None,
                        "task_name": None,
                        "task_version": None,
                        "consumer_name": None,
                        "user_id": str(item.user_id),
                        "correlation_id": None,
                        "trace_id": None,
                        "attempt": item.publish_attempt,
                        "worker_id": self._worker_id,
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                        "status": "quarantined",
                        "error_code": item.decode_error or "malformed_outbox_event",
                    },
                )
                continue
            event = item.event
            try:
                # 按路由表把事件转成任务信封；路由表不认识的事件说明 schema 不支持。
                tasks = route_event(event, enqueued_at=self._clock.now())
            except DomainError:
                await self._repository.quarantine(
                    event_id=event.event_id,
                    worker_id=self._worker_id,
                    quarantined_at=self._clock.now(),
                    error_code="unsupported_durable_event_schema",
                )
                quarantined += 1
                logger.error(
                    "outbox.event.quarantined",
                    extra={
                        "event_id": str(event.event_id),
                        "event_type": event.event_type,
                        "schema_version": event.schema_version,
                        "task_name": None,
                        "task_version": None,
                        "consumer_name": None,
                        "user_id": str(event.user_id),
                        "correlation_id": str(event.metadata.correlation_id),
                        "trace_id": (
                            str(event.metadata.trace_id)
                            if event.metadata.trace_id is not None
                            else None
                        ),
                        "attempt": item.publish_attempt,
                        "worker_id": self._worker_id,
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                        "status": "quarantined",
                        "error_code": "unsupported_durable_event_schema",
                    },
                )
                continue
            try:
                for task in tasks:
                    await self._queue.enqueue(task)
            except Exception as exc:
                # Redis / adapter 异常只在 publisher 基础设施边界归一化；
                # event 与已成功入队的 task 都保留原 identity，重试允许重复。
                delay = retry_delay(attempt=item.publish_attempt, event_id=event.event_id)
                await self._repository.reschedule(
                    event_id=event.event_id,
                    worker_id=self._worker_id,
                    available_at=self._clock.now() + delay,
                    error_code="queue_enqueue_failed",
                )
                rescheduled += 1
                logger.warning(
                    "outbox.event.rescheduled",
                    extra={
                        "event_id": str(event.event_id),
                        "event_type": event.event_type,
                        "user_id": str(event.user_id),
                        "worker_id": self._worker_id,
                        "attempt": item.publish_attempt,
                        "error_code": "queue_enqueue_failed",
                    },
                    exc_info=exc,
                )
                continue
            # 全部任务入队成功：标记 published；后续执行由 consumer 负责。
            await self._repository.mark_published(
                event_id=event.event_id,
                worker_id=self._worker_id,
                published_at=self._clock.now(),
            )
            published += 1
            logger.info(
                "outbox.event.published",
                extra={
                    "event_id": str(event.event_id),
                    "event_type": event.event_type,
                    "schema_version": event.schema_version,
                    "task_name": ",".join(task.task_name for task in tasks),
                    "task_version": ",".join(str(task.task_version) for task in tasks),
                    "consumer_name": ",".join(task.task_name for task in tasks),
                    "user_id": str(event.user_id),
                    "correlation_id": str(event.metadata.correlation_id),
                    "trace_id": (
                        str(event.metadata.trace_id)
                        if event.metadata.trace_id is not None
                        else None
                    ),
                    "attempt": item.publish_attempt,
                    "worker_id": self._worker_id,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "status": "published",
                    "error_code": None,
                },
            )
        return PublishBatchResult(
            claimed=len(claimed),
            published=published,
            rescheduled=rescheduled,
            quarantined=quarantined,
        )
