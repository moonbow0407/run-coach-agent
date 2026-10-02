"""pytest 共享 fixture：集成/场景测试用的数据库、应用装配与 HTTP 客户端基础设施。"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.bootstrap import create_app
from app.common.clock import FrozenClock
from app.common.ids import new_id
from app.infrastructure.auth.jwt import issue_token
from app.infrastructure.config import Settings
from app.infrastructure.database import models as _models  # noqa: F401
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import create_session_factory, short_session

# 测试数据库连接串含本机凭据，不允许默认值入库：必须通过环境变量显式提供
# （README「验证」一节），且延迟到 fixture 内读取，保证只跑单元测试时无需配置。
TEST_NOW = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"环境变量 {name} 未设置：集成/场景测试需要指向本机 PostgreSQL 的连接串，"
            "运行 pytest 前请按 README「验证」一节显式导出"
        )
    return value


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """整个测试会话共享的配置：指向测试库、关闭真实 LLM。"""
    return Settings(
        database_url=_required_env("TEST_DATABASE_URL"),
        jwt_secret="test-secret-must-be-at-least-32-bytes",
        jwt_expire_seconds=3600,
        llm_api_key=None,
        agent_max_steps=8,
        conversation_history_limit=20,
    )


@pytest.fixture(scope="session")
def clock() -> FrozenClock:
    """会话级冻结时钟：固定在 TEST_NOW，使业务时间判定可复现。"""
    return FrozenClock(TEST_NOW)


@pytest.fixture(scope="session")
async def engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """会话级异步引擎：确保测试库存在、重建 schema 并执行 Alembic 迁移。"""
    admin = create_async_engine(
        _required_env("ADMIN_DATABASE_URL"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        # 管理员连接（AUTOCOMMIT）：确保测试库 run_coach_test 存在，不存在则创建
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = 'run_coach_test'")
            )
            if not exists:
                await conn.execute(text("CREATE DATABASE run_coach_test"))
    finally:
        await admin.dispose()

    engine = create_async_engine(test_settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    # 重建 public schema：每个测试会话都从空库开始
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # 用正式 Alembic 迁移建表，测试不维护第二套 DDL
    await asyncio.to_thread(_upgrade_test_database, test_settings.database_url)
    # 生成器 fixture：yield 前是 setup，yield 后是 teardown
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """会话级 sessionmaker：由各测试自行决定事务与提交边界。"""
    return create_session_factory(engine)


@pytest.fixture
async def clean_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """函数级清理：测试结束后 TRUNCATE 全部表，防止数据串场。"""
    # 生成器 fixture：setup 为空，teardown 统一清库
    yield
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def user_id(sessions: async_sessionmaker[AsyncSession], clock: FrozenClock) -> UUID:
    """函数级：预置一个用户行并返回其 id，作为各测试数据的归属主体。"""
    uid = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=uid, created_at=clock.now(), updated_at=clock.now()))
    return uid


@pytest.fixture
def auth_header(user_id: UUID, test_settings: Settings) -> dict[str, str]:
    """函数级：为预置用户签发 JWT，返回可直接携带的 Authorization 头。"""
    return {"Authorization": f"Bearer {token_for(user_id, test_settings)}"}


def token_for(user_id: UUID, settings: Settings, clock: FrozenClock | None = None) -> str:
    """签发供 HTTP 鉴权使用的测试 JWT。"""
    # JWT 校验使用墙上时钟。测试 Clock 冻结在 08:00 会导致 iat 落在未来而被拒。
    now = datetime.now(UTC)
    return issue_token(
        user_id=user_id,
        secret=settings.jwt_secret,
        now=now,
        expire_seconds=settings.jwt_expire_seconds,
        algorithm=settings.jwt_algorithm,
    )


@pytest.fixture
async def make_app(test_settings: Settings, clock: FrozenClock, engine: AsyncEngine):
    """工厂 fixture：按需创建装配了替身依赖的 app；teardown 统一释放其数据库引擎。"""
    apps: list = []

    def _make(
        *,
        reasoner=None,
        memory_extractor=None,
        embedding_provider=None,
        episode_detector=None,
    ):
        app = create_app(
            test_settings,
            reasoner=reasoner,
            clock=clock,
            poolclass=NullPool,
            memory_extractor=memory_extractor,
            embedding_provider=embedding_provider,
            episode_detector=episode_detector,
        )
        apps.append(app)
        return app

    yield _make
    # teardown：关闭本测试创建的所有 app 的连接池
    for app in apps:
        await app.state.engine.dispose()


@pytest.fixture
async def client_factory():
    """返回异步 HTTP 客户端工厂（ASGI 内存传输，不经过真实网络）。"""
    async def _client(app):
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _client


def _upgrade_test_database(database_url: str) -> None:
    """使用正式 Alembic revision 建立集成测试数据库。"""
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    alembic_command.upgrade(config, "head")
