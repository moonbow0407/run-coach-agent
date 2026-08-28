from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import Pool


def create_engine(database_url: str, *, poolclass: type[Pool] | None = None) -> AsyncEngine:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if poolclass is not None:
        kwargs["poolclass"] = poolclass
    return create_async_engine(database_url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def short_session(
    factory: async_sessionmaker[AsyncSession],
    *,
    commit: bool = False,
) -> AsyncIterator[AsyncSession]:
    """打开一次短生命周期 session。

    事务不得跨越 LLM 或 Capability 执行。每个 Store / Provider / Capability
    调用都应使用独立 short_session，而不是复用请求级长事务。
    """
    async with factory() as session:
        try:
            yield session
            if commit:
                await session.commit()
        except Exception:
            await session.rollback()
            raise
