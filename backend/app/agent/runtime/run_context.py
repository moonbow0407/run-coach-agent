"""AgentRuntime 的输入命令：由 ChatService 从可信 RequestContext 构造。

Runtime 不接触 HTTP 对象，所有身份与追踪信息都通过这里传入。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AgentTurnCommand:
    """驱动一次 AgentRun 的全部可信信息。

    user_id 来自认证系统；current_input 是本轮用户输入原文。
    """

    user_id: UUID
    thread_id: UUID
    turn_id: UUID
    run_id: UUID
    request_id: UUID
    trace_id: UUID
    timestamp: datetime
    current_input: str
