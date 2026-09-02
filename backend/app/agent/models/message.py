"""Canonical Conversation 的消息模型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


# StrEnum：成员既是枚举又是字符串，可直接比较与序列化进存储 / Prompt
class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


# frozen=True：不可变数据类，消息落库后不允许修改
@dataclass(frozen=True)
class Message:
    """Canonical Conversation 消息。只保存 user / assistant，不保存工具调用。"""

    id: UUID
    thread_id: UUID  # 所属会话线程
    turn_id: UUID  # 所属对话轮次
    role: MessageRole  # 消息角色：仅 user / assistant 两种
    content: str  # 消息正文
    created_at: datetime  # 创建时间
