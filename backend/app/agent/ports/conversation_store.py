"""会话写端口：Conversation 生命周期（开始 / 提交 / 失败 / 取消）的事务边界。

每个方法对应一次独立短事务，保证事务不跨越 LLM 调用（ARCHITECTURE §44）。
实现方负责校验用户归属（user_id 匹配）与状态合法性。
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.agent.models.message import Message
from app.agent.models.run import AgentRun
from app.agent.models.thread import Thread
from app.agent.models.turn import Turn


@dataclass(frozen=True)
class StartedTurn:
    """start_turn 的产物：新 Turn、用户消息与 AgentRun 均已落库。"""

    thread: Thread
    turn: Turn
    user_message: Message
    run: AgentRun


@dataclass(frozen=True)
class CommittedTurn:
    """commit_turn 的产物：助手消息已落库，Turn 置为 committed。"""

    thread: Thread
    turn: Turn
    assistant_message: Message
    run: AgentRun


class ConversationStore(Protocol):
    """Conversation 生命周期的事务边界。每个方法都是一次短事务。"""

    async def start_turn(
        self,
        *,
        user_id: UUID,
        thread_id: UUID | None,
        content: str,
    ) -> StartedTurn:
        ...

    async def commit_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        assistant_content: str,
    ) -> CommittedTurn:
        ...

    async def fail_turn(self, *, user_id: UUID, turn_id: UUID) -> None:
        ...

    async def cancel_turn(self, *, user_id: UUID, turn_id: UUID) -> None:
        ...
