"""面向人工验收的运行时演示数据：创建演示用户并写入默认场景。

Scenario Lab 与 dev 场景 API 共用 `seed_scenario`；本模块只补上
「创建用户行」这一步（场景 API 面向已登录用户，脚本 seed 则现场建用户）。
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.athlete_recompute_service import AthleteStateRecomputeService
from app.coaching.application.workout_command_service import (
    WorkoutCommandService,
    WorkoutFeedbackCommandService,
)
from app.common.clock import Clock
from app.common.ids import new_id
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.scenario import DEMO_SPEC, ScenarioSeed, seed_scenario


async def seed_demo(
    sessions: async_sessionmaker[AsyncSession],
    *,
    workout_command_service: WorkoutCommandService,
    workout_feedback_command_service: WorkoutFeedbackCommandService,
    athlete_recompute_service: AthleteStateRecomputeService,
    clock: Clock,
    user_id: UUID | None = None,
) -> ScenarioSeed:
    """创建以当前时钟为锚点、可直接触发 Plan Adaptation 的演示数据。

    用户行在此一次短事务中创建，其余（目标/计划/训练/反馈/状态）统一走
    ScenarioSpec 种子路径，保证脚本与 Scenario Lab 只有一套假数据来源。
    """
    anchor = clock.now()
    user_id = user_id or new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=user_id, created_at=anchor, updated_at=anchor))
    return await seed_scenario(
        sessions,
        user_id=user_id,
        spec=DEMO_SPEC,
        anchor=anchor,
        workout_command_service=workout_command_service,
        workout_feedback_command_service=workout_feedback_command_service,
        athlete_recompute_service=athlete_recompute_service,
        clock=clock,
    )
