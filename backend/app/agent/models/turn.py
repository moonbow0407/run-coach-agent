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
    PENDING = "pending"  # 已创建，尚未开始执行
    RUNNING = "running"  # 推理循环进行中
    COMMITTED = "committed"  # 成功提交，消息进入历史上下文
    FAILED = "failed"  # 执行失败（终态）
    CANCELLED = "cancelled"  # 被取消（终态，属正常语义而非错误）


# frozen=True：不可变数据类，Turn 状态推进通过整体替换实例完成
@dataclass(frozen=True)
class Turn:
    """一轮交互。user_message_id 在开始时写入，assistant_message_id 提交成功后才有值。"""

    id: UUID
    thread_id: UUID  # 所属会话线程
    user_id: UUID  # 归属用户
    user_message_id: UUID
    assistant_message_id: UUID | None
    status: TurnStatus  # 当前状态（见 TurnStatus）
    started_at: datetime  # 开始时间
    committed_at: datetime | None  # 提交时间，仅 committed 后有值
