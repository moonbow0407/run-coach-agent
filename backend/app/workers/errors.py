"""Worker boundary 的可重试 / 永久失败分类。"""


class WorkerError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TransientWorkerError(WorkerError):
    pass


class PermanentWorkerError(WorkerError):
    pass


class WorkerRetryRequested(WorkerError):
    """Queue adapter 据此安排 delayed retry，不把 delivery 当成功 ack。"""

    def __init__(self, code: str, *, defer_seconds: int) -> None:
        super().__init__(code)
        self.defer_seconds = defer_seconds
