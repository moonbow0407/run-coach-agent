"""Worker boundary 的可重试 / 永久失败分类。"""


class WorkerError(Exception):
    """Worker 边界错误基类。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code  # 结构化错误码：写入日志与消费回执，便于归类统计


class TransientWorkerError(WorkerError):
    """临时性失败：重试有可能成功（如数据库抖动、外部服务超时）。"""


class PermanentWorkerError(WorkerError):
    """永久性失败：重试无意义（如 schema 不合法、任务路由未知）。"""


class WorkerRetryRequested(WorkerError):
    """Queue adapter 据此安排 delayed retry，不把 delivery 当成功 ack。"""

    def __init__(self, code: str, *, defer_seconds: int) -> None:
        super().__init__(code)
        self.defer_seconds = defer_seconds  # 延迟重投秒数（下一次投递的等待时间）
