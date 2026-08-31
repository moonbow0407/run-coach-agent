"""Memory 生命周期维护命令。"""

from datetime import datetime
from uuid import UUID

from app.memory.ports.repositories import MemoryRepository


class MemoryLifecycleService:
    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def expire_due(self, *, user_id: UUID, as_of: datetime) -> int:
        return await self._repository.expire_due(user_id=user_id, as_of=as_of)
