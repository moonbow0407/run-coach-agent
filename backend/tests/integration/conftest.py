"""集成测试专用 fixture：在根 conftest 基础上提供垂直切片 seed 与对应认证头。"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import Settings
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.vertical_slice import VerticalSliceSeed, seed_vertical_slice
from tests.conftest import token_for


@pytest.fixture(autouse=True)
async def _clean_integration_tables(clean_tables) -> None:
    """autouse fixture：每个集成测试结束后 TRUNCATE 全部表，保证用例间互不残留数据。"""
    # fixture 生成器：yield 前是 setup，yield 后是 teardown；清库动作在根 conftest 的 clean_tables 中执行。
    yield


@pytest.fixture
async def slice_seed(sessions: async_sessionmaker[AsyncSession]) -> VerticalSliceSeed:
    """写入垂直切片 seed 数据（用户/目标/计划/课次/反馈/状态快照），返回其句柄。"""
    # short_session：独立短事务写入并立即提交，测试主体再通过应用自身连接读取。
    async with short_session(sessions, commit=True) as session:
        return await seed_vertical_slice(session)


@pytest.fixture
def slice_auth_header(
    slice_seed: VerticalSliceSeed,
    test_settings: Settings,
) -> dict[str, str]:
    """为 seed 用户签发 JWT，返回可直接用于 HTTP 请求的 Authorization 头。"""
    return {"Authorization": f"Bearer {token_for(slice_seed.user_id, test_settings)}"}
