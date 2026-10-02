"""用户维度 Domain Mutation 锁：Athlete State append 与 Plan Activation 共用。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import NotFoundError
from app.infrastructure.database.models.user import UserRow


async def lock_user_row(session: AsyncSession, user_id: UUID) -> None:
    """SELECT users WHERE id = user_id FOR UPDATE。用户不存在则 fail fast。"""
    row = await session.scalar(select(UserRow).where(UserRow.id == user_id).with_for_update())
    if row is None:
        raise NotFoundError("用户不存在")
