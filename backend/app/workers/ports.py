"""Worker 对 queue infrastructure 的最小端口。

发布方只依赖“能入队”这一能力本身，具体投递由 infrastructure 层适配（当前为 arq）。
"""

from datetime import timedelta
from typing import Protocol

from app.workers.contracts import WorkerTaskEnvelope


class QueuePublisher(Protocol):
    """队列发布端口。

    Protocol（结构化鸭子类型）：实现方无需继承本类，方法签名一致即视为实现。
    """

    # 把任务信封放入队列；defer_by 指定延迟投递（用于重试退避）。
    async def enqueue(
        self, task: WorkerTaskEnvelope, *, defer_by: timedelta | None = None
    ) -> None: ...
