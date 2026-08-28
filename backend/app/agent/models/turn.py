"""Turn：一次“用户提问 → 助手回答”的完整交互单元。

Turn 是对话的事务与状态边界：
    pending / running   进行中
    committed           成功提交，消息进入历史上下文
    failed / cancelled  终态失败，用户消息保留但不进入正常上下文
只有 committed Turn 的消息才会作为历史对话参与后续推理。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TurnStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Turn:
    """一轮交互。user_message_id 在开始时写入，assistant_message_id 提交成功后才有值。"""

    id: UUID
    thread_id: UUID
    user_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID | None
    status: TurnStatus
    started_at: datetime
    committed_at: datetime | None
