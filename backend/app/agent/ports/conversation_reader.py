from typing import Protocol
from uuid import UUID

from app.agent.models.message import Message
from app.agent.models.thread import Thread


class ConversationReader(Protocol):
    async def get_thread(self, *, user_id: UUID, thread_id: UUID) -> Thread | None:
        ...

    async def list_committed_messages(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID | None,
        limit: int,
    ) -> list[Message]:
        ...
