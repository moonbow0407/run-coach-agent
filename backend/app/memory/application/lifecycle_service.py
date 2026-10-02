"""Memory 生命周期维护命令。"""

from datetime import datetime
from uuid import UUID

from app.memory.ports.repositories import MemoryRepository


class MemoryLifecycleService:
    """记忆生命周期维护命令的薄封装：实际处理在仓储实现中完成。"""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository  # Memory 仓储端口

    async def expire_due(self, *, user_id: UUID, as_of: datetime) -> int:
        """把 as_of 时刻已到期的记忆标记为过期，返回处理条数。"""
        return await self._repository.expire_due(user_id=user_id, as_of=as_of)
