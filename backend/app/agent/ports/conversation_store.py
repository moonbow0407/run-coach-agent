from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.agent.models.message import Message
from app.agent.models.run import AgentRun
from app.agent.models.thread import Thread
from app.agent.models.turn import Turn


@dataclass(frozen=True)
class StartedTurn:
    thread: Thread
    turn: Turn
    user_message: Message
    run: AgentRun


@dataclass(frozen=True)
class CommittedTurn:
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
