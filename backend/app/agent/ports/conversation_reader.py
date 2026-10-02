"""会话只读端口：查询线程与已提交消息。

供 API 历史消息接口与上下文装配使用；只暴露已提交（committed）内容。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.agent.models.message import Message
from app.agent.models.thread import Thread
from app.agent.models.turn import Turn


@dataclass(frozen=True)
class CommittedTurnMessages:
    """Projector 可读取的 canonical committed Turn，不暴露 RunStep。"""

    turn_id: UUID
    user_message: Message  # 本轮用户消息
    assistant_message: Message  # 本轮助手回复
    committed_at: datetime  # 提交时间


# Protocol（结构化鸭子类型）：只约束方法签名，实现方无需显式继承本类
class ConversationReader(Protocol):
    """会话历史只读接口，实现在 infrastructure 层。"""

    # 按 ID 查询用户名下的 Turn（不限状态）
    async def get_turn(self, *, user_id: UUID, turn_id: UUID) -> Turn | None: ...

    # 按 ID 查询用户名下的会话线程
    async def get_thread(self, *, user_id: UUID, thread_id: UUID) -> Thread | None: ...

    # 按时间顺序读取线程内已提交消息；exclude_turn_id 用于排除当前轮
    async def list_committed_messages(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID | None,
        limit: int,
    ) -> list[Message]: ...

    # 读取某个已提交 Turn 的成对消息（用户 + 助手），供 Projector 使用
    async def get_committed_turn_messages(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
    ) -> CommittedTurnMessages | None: ...
