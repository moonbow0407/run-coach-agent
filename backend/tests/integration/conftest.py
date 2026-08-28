import pytest


@pytest.fixture(autouse=True)
async def _clean_integration_tables(clean_tables) -> None:
    yield
