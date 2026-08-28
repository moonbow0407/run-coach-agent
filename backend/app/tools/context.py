"""可信执行上下文：由 Runtime 构造，模型不可控。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ToolExecutionContext:
    """工具执行的可信运行信息。

    八个字段全部由 Runtime 构造：user_id 只来自认证系统产生的
    RequestContext，call_id 是本次调用的内部 UUID（用于 Lifecycle 与
    RunStep Trace），timestamp 是本次请求的统一时间基准。
    工具参数模型不得声明这些字段；模型尝试注入的身份信息会被
    参数校验（extra="forbid"）直接拒绝。
    """

    user_id: UUID
    thread_id: UUID
    turn_id: UUID
    run_id: UUID
    call_id: UUID
    request_id: UUID
    trace_id: UUID
    timestamp: datetime
