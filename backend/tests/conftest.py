from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.bootstrap import create_app
from app.common.clock import FrozenClock
from app.common.ids import new_id
from app.infrastructure.auth.jwt import issue_token
from app.infrastructure.config import Settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import *  # noqa: F403
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import create_session_factory, short_session

TEST_DATABASE_URL = (
    "postgresql+asyncpg://run_coach:run_coach@localhost:5433/run_coach_test"
)
ADMIN_DATABASE_URL = "postgresql+asyncpg://run_coach:run_coach@localhost:5433/postgres"
TEST_NOW = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        jwt_secret="test-secret-must-be-at-least-32-bytes",
        jwt_expire_seconds=3600,
        llm_api_key=None,
        agent_max_steps=8,
        conversation_history_limit=20,
    )


@pytest.fixture(scope="session")
def clock() -> FrozenClock:
    return FrozenClock(TEST_NOW)


@pytest.fixture(scope="session")
async def engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    admin = create_async_engine(
        ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = 'run_coach_test'")
            )
            if not exists:
                await conn.execute(text("CREATE DATABASE run_coach_test"))
    finally:
        await admin.dispose()

    engine = create_async_engine(
        test_settings.database_url, pool_pre_ping=True, poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def clean_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def user_id(sessions: async_sessionmaker[AsyncSession], clock: FrozenClock) -> UUID:
    uid = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=uid, created_at=clock.now(), updated_at=clock.now()))
    return uid


@pytest.fixture
def auth_header(user_id: UUID, test_settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id, test_settings)}"}


def token_for(user_id: UUID, settings: Settings, clock: FrozenClock | None = None) -> str:
    # JWT 校验使用墙上时钟。测试 Clock 冻结在 08:00 会导致 iat 落在未来而被拒。
    now = datetime.now(timezone.utc)
    return issue_token(
        user_id=user_id,
        secret=settings.jwt_secret,
        now=now,
        expire_seconds=settings.jwt_expire_seconds,
        algorithm=settings.jwt_algorithm,
    )


@pytest.fixture
async def make_app(test_settings: Settings, clock: FrozenClock, engine: AsyncEngine):
    apps: list = []

    def _make(*, reasoner=None):
        app = create_app(
            test_settings, reasoner=reasoner, clock=clock, poolclass=NullPool
        )
        apps.append(app)
        return app

    yield _make
    for app in apps:
        await app.state.engine.dispose()


@pytest.fixture
async def client_factory():
    async def _client(app):
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _client
