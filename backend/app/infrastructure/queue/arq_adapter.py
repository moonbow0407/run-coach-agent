"""ARQ queue adapter；Redis 只保存 operational job state。"""

import logging
from datetime import timedelta

from arq.connections import ArqRedis

from app.workers.contracts import WorkerTaskEnvelope

logger = logging.getLogger(__name__)


class ArqQueuePublisher:
    """arq 任务队列发布器：把待消费任务推入 Redis 队列。"""

    def __init__(self, redis: ArqRedis, *, queue_name: str) -> None:
        self._redis = redis
        self._queue_name = queue_name

    async def enqueue(
        self,
        task: WorkerTaskEnvelope,
        *,
        defer_by: timedelta | None = None,
    ) -> None:
        """投递一个消费任务；job_id 用事件 ID，天然防止重复入队。"""
        job = await self._redis.enqueue_job(
            "consume_durable_task",
            task.to_dict(),
            _job_id=task.job_id,  # 以 job_id 幂等：同 ID 任务已在队列则不入队
            _queue_name=self._queue_name,
            _defer_by=defer_by,  # 延迟投递（对齐 outbox 的 available_at）
        )
        logger.info(
            "worker.task.enqueued",
            extra={
                "event_id": str(task.event.event_id),
                "event_type": task.event.event_type,
                "task_name": task.task_name,
                "task_version": task.task_version,
                "user_id": str(task.event.user_id),
                "correlation_id": str(task.event.metadata.correlation_id),
                "trace_id": (
                    str(task.event.metadata.trace_id)
                    if task.event.metadata.trace_id is not None
                    else None
                ),
                "status": "enqueued" if job is not None else "already_enqueued",
            },
        )
