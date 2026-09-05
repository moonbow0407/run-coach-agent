"""AgentRuntime 的输入命令：由 ChatService 从可信 RequestContext 构造。

Runtime 不接触 HTTP 对象，所有身份与追踪信息都通过这里传入。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


# frozen=True：不可变数据类，命令对象在传递途中不允许被篡改
@dataclass(frozen=True)
class AgentTurnCommand:
    """驱动一次 AgentRun 的全部可信信息。

    user_id 来自认证系统；current_input 是本轮用户输入原文。
    resume=True 时从该 run_id 的最新检查点继续 Reason–Act。
    """

    user_id: UUID  # 认证系统给出的用户身份，Runtime 不再自行鉴权
    thread_id: UUID  # 会话线程
    turn_id: UUID  # 本轮对话
    run_id: UUID  # 本次 Agent 推理运行
    request_id: UUID  # HTTP 请求 ID，事件按此隔离到对应 SSE 连接
    trace_id: UUID  # 追踪 ID，贯穿日志与执行轨迹
    timestamp: datetime  # 请求的可信时间基准
    current_input: str  # 本轮用户输入原文
    resume: bool = False  # True=从最新检查点续跑，不再从零开始
