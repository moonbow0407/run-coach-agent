"""ARQ queue adapter；Redis 只保存 operational job state。"""

import logging
from datetime import timedelta

from arq.connections import ArqRedis

from app.workers.contracts import WorkerTaskEnvelope

logger = logging.getLogger(__name__)


class ArqQueuePublisher:
    def __init__(self, redis: ArqRedis, *, queue_name: str) -> None:
        self._redis = redis
        self._queue_name = queue_name

    async def enqueue(
        self,
        task: WorkerTaskEnvelope,
        *,
        defer_by: timedelta | None = None,
    ) -> None:
        job = await self._redis.enqueue_job(
            "consume_durable_task",
            task.to_dict(),
            _job_id=task.job_id,
            _queue_name=self._queue_name,
            _defer_by=defer_by,
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
