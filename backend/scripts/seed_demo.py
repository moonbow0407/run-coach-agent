"""创建可直接验收 Plan Adaptation 的运行时演示数据。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import build_container
from app.common.clock import SystemClock
from app.infrastructure.config import Settings
from app.infrastructure.seed.demo import seed_demo


async def main() -> None:
    """装配应用容器并写入演示数据；结束后释放数据库连接池。"""
    settings = Settings()
    container = build_container(settings, clock=SystemClock())
    try:
        seed = await seed_demo(
            container.sessions,
            workout_command_service=container.workout_command_service,
            workout_feedback_command_service=container.workout_feedback_command_service,
            athlete_recompute_service=container.athlete_recompute_service,
            clock=container.clock,
        )
    finally:
        # 无论写入成败都释放连接池。
        await container.engine.dispose()
    print(
        f"seeded demo user_id={seed.user_id} "
        f"athlete_state_version={seed.athlete_state_version}"
    )


if __name__ == "__main__":
    asyncio.run(main())
