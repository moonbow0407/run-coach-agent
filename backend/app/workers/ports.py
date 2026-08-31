"""Worker 对 queue infrastructure 的最小端口。"""

from datetime import timedelta
from typing import Protocol

from app.workers.contracts import WorkerTaskEnvelope


class QueuePublisher(Protocol):
    async def enqueue(
        self, task: WorkerTaskEnvelope, *, defer_by: timedelta | None = None
    ) -> None: ...
