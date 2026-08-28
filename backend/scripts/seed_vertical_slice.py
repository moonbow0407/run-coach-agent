"""写入 Phase 1 垂直切片 seed 数据。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.config import Settings
from app.infrastructure.database.session import create_engine, create_session_factory, short_session
from app.infrastructure.seed.vertical_slice import seed_vertical_slice


async def main() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    await engine.dispose()
    print(f"seeded user_id={seed.user_id}")


if __name__ == "__main__":
    asyncio.run(main())
