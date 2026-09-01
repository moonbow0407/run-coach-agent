"""面向人工验收的运行时演示数据。"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.athlete_recompute_service import AthleteStateRecomputeService
from app.coaching.application.workout_command_service import (
    WorkoutCommandService,
    WorkoutFeedbackCommandService,
)
from app.coaching.domain.workout.models import WorkoutSource, WorkoutType
from app.coaching.ports.workout_mutation_store import WorkoutFeedbackMutation, WorkoutMutation
from app.common.clock import Clock
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import (
    PlannedSessionRow,
    TrainingGoalRow,
    TrainingPlanRow,
)
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session


@dataclass(frozen=True)
class DemoSeed:
    """演示数据句柄；包含人工 E2E 所需的用户与状态版本。"""

    user_id: UUID
    goal_id: UUID
    plan_id: UUID
    workout_ids: tuple[UUID, ...]
    athlete_state_version: int


async def seed_demo(
    sessions: async_sessionmaker[AsyncSession],
    *,
    workout_command_service: WorkoutCommandService,
    workout_feedback_command_service: WorkoutFeedbackCommandService,
    athlete_recompute_service: AthleteStateRecomputeService,
    clock: Clock,
    user_id: UUID | None = None,
) -> DemoSeed:
    """创建以当前时钟为锚点、可直接触发 Plan Adaptation 的演示数据。

    Goal / Plan 当前没有独立的在线 mutation command，因此在一次短事务中创建
    它们；Workout、Feedback 与 Athlete State 则统一走 Phase 5 canonical
    mutation / Outbox 路径，确保启动 Worker 后也能验证持续投影链路。
    """
    anchor = clock.now()
    user_id = user_id or new_id()
    goal_id = new_id()
    plan_id = new_id()

    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=user_id, created_at=anchor, updated_at=anchor))
        await session.flush()
        session.add(
            TrainingGoalRow(
                id=goal_id,
                user_id=user_id,
                goal_type="race",
                race_date=anchor.date() + timedelta(days=45),
                race_distance_m=21097,
                target_time_s=6600,
                status="active",
                created_at=anchor,
                updated_at=anchor,
            )
        )
        session.add(
            TrainingPlanRow(
                id=plan_id,
                user_id=user_id,
                version=1,
                goal_id=goal_id,
                status="active",
                starts_on=anchor.date() - timedelta(days=14),
                ends_on=anchor.date() + timedelta(days=56),
                created_at=anchor - timedelta(days=14),
            )
        )
        await session.flush()
        for days_from_anchor, session_type, title, prescription in (
            (1, "easy", "恢复轻松跑", {"distance_m": 7000, "pace": "5:50-6:10"}),
            (2, "tempo", "本周节奏跑", {"distance_m": 9000, "pace": "5:10"}),
            (4, "interval", "本周间歇训练", {"reps": 6, "distance_m": 1000}),
        ):
            session.add(
                PlannedSessionRow(
                    id=new_id(),
                    plan_id=plan_id,
                    scheduled_date=anchor.date() + timedelta(days=days_from_anchor),
                    session_type=session_type,
                    title=title,
                    prescription=prescription,
                )
            )

    workout_ids: list[UUID] = []
    for days_ago, workout_type, duration_s, distance_m in (
        (6, WorkoutType.EASY, 2700, 7500.0),
        (3, WorkoutType.TEMPO, 3000, 9500.0),
        (1, WorkoutType.INTERVAL, 2520, 8000.0),
    ):
        workout = await workout_command_service.record(
            user_id=user_id,
            mutation=WorkoutMutation(
                started_at=anchor - timedelta(days=days_ago),
                distance_m=distance_m,
                duration_s=duration_s,
                avg_heart_rate=165 if workout_type is WorkoutType.INTERVAL else 150,
                max_heart_rate=181 if workout_type is WorkoutType.INTERVAL else 172,
                workout_type=workout_type,
                source=WorkoutSource.SEED,
            ),
            event_metadata=EventMetadata(correlation_id=new_id()),
        )
        workout_ids.append(workout.id)

    await workout_feedback_command_service.record(
        user_id=user_id,
        workout_id=workout_ids[-1],
        mutation=WorkoutFeedbackMutation(
            perceived_exertion=9,
            subjective_fatigue=9,
            soreness=8,
            note="最后两组间歇明显掉速，今天腿很酸",
        ),
        event_metadata=EventMetadata(correlation_id=new_id()),
    )
    snapshot = await athlete_recompute_service.recompute(
        user_id=user_id,
        as_of=clock.now(),
        event_metadata=EventMetadata(correlation_id=new_id()),
    )
    return DemoSeed(
        user_id=user_id,
        goal_id=goal_id,
        plan_id=plan_id,
        workout_ids=tuple(workout_ids),
        athlete_state_version=snapshot.version,
    )
