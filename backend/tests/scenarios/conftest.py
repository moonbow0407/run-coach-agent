"""端到端教练场景测试（scenarios）的共享 fixture：负责清库、播种演示数据与生成鉴权头。"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import Settings
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.vertical_slice import VerticalSliceSeed, seed_vertical_slice
from tests.conftest import token_for


@pytest.fixture(autouse=True)
async def _clean_scenario_tables(clean_tables) -> None:
    """本包所有场景测试自动复用 clean_tables：测试后清空全部业务表，场景之间互不残留。"""
    yield  # 生成器 fixture：yield 前为 setup，yield 后为 teardown（清理由 clean_tables 完成）。


@pytest.fixture
async def slice_seed(sessions: async_sessionmaker[AsyncSession]) -> VerticalSliceSeed:
    """播种垂直切片：演示用户 + 半马目标 + v1 计划 + 四次训练 + 状态快照，返回 ID 句柄。"""
    async with short_session(sessions, commit=True) as session:
        return await seed_vertical_slice(session)


@pytest.fixture
def slice_auth_header(
    slice_seed: VerticalSliceSeed,
    test_settings: Settings,
) -> dict[str, str]:
    """为 seed 用户签发 JWT，构造可直接调用 HTTP 接口的 Authorization 头。"""
    return {
        # token_for：按测试配置给用户签发访问令牌。
        "Authorization": f"Bearer {token_for(slice_seed.user_id, test_settings)}"
    }
