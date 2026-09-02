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
    thread_id: UUID  # 会话线程 ID（用户的历次对话串在其下）
    turn_id: UUID  # 当前 Turn（一轮对话）ID
    run_id: UUID  # 当前 Run（一次 Agent 推理运行）ID
    call_id: UUID
    request_id: UUID  # 请求级链路追踪 ID
    trace_id: UUID  # 跨服务链路追踪 ID
    timestamp: datetime
