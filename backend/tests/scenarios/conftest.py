import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.config import Settings
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.vertical_slice import VerticalSliceSeed, seed_vertical_slice
from tests.conftest import token_for


@pytest.fixture(autouse=True)
async def _clean_scenario_tables(clean_tables) -> None:
    yield


@pytest.fixture
async def slice_seed(sessions: async_sessionmaker[AsyncSession]) -> VerticalSliceSeed:
    async with short_session(sessions, commit=True) as session:
        return await seed_vertical_slice(session)


@pytest.fixture
def slice_auth_header(
    slice_seed: VerticalSliceSeed,
    test_settings: Settings,
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token_for(slice_seed.user_id, test_settings)}"
    }
