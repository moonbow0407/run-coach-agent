from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import new_id
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlannedSessionRow,
    TrainingGoalRow,
    TrainingPlanRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.database.models.user import UserRow

SLICE_NOW = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class VerticalSliceSeed:
    user_id: UUID
    goal_id: UUID
    plan_id: UUID
    workout_ids: tuple[UUID, ...]


async def seed_vertical_slice(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
) -> VerticalSliceSeed:
    """文档 §47 垂直切片所需的 Goal / Workouts / Plan / AthleteStateSnapshot。

    AthleteStateSnapshot 是 fixture，不代表 Phase 1 实现了状态算法。
    """
    now = SLICE_NOW
    user_id = user_id or new_id()
    session.add(UserRow(id=user_id, created_at=now, updated_at=now))
    await session.flush()

    goal_id = new_id()
    session.add(
        TrainingGoalRow(
            id=goal_id,
            user_id=user_id,
            goal_type="race",
            race_date=date(2026, 10, 18),
            race_distance_m=21097,
            target_time_s=6600,
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()

    workouts = [
        ("easy", datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc), 8000.0, 2880, 142, 158),
        ("tempo", datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc), 10000.0, 3000, 158, 172),
        ("long_run", datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc), 18000.0, 6600, 148, 165),
        ("interval", datetime(2026, 8, 27, 6, 0, tzinfo=timezone.utc), 8000.0, 2520, 168, 181),
    ]
    workout_ids: list[UUID] = []
    for workout_type, started_at, distance_m, duration_s, avg_hr, max_hr in workouts:
        workout_id = new_id()
        workout_ids.append(workout_id)
        session.add(
            WorkoutRow(
                id=workout_id,
                user_id=user_id,
                started_at=started_at,
                distance_m=distance_m,
                duration_s=duration_s,
                avg_heart_rate=avg_hr,
                max_heart_rate=max_hr,
                workout_type=workout_type,
                source="seed",
                created_at=started_at,
            )
        )
    await session.flush()

    session.add(
        WorkoutFeedbackRow(
            id=new_id(),
            user_id=user_id,
            workout_id=workout_ids[-1],
            perceived_exertion=8,
            subjective_fatigue=7,
            soreness=6,
            note="最后两组间歇明显掉速",
            created_at=datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc),
        )
    )

    plan_id = new_id()
    session.add(
        TrainingPlanRow(
            id=plan_id,
            user_id=user_id,
            version=1,
            goal_id=goal_id,
            status="active",
            starts_on=date(2026, 7, 20),
            ends_on=date(2026, 9, 27),
            created_at=now - timedelta(days=30),
        )
    )
    await session.flush()
    session.add(
        PlannedSessionRow(
            id=new_id(),
            plan_id=plan_id,
            scheduled_date=date(2026, 8, 29),
            session_type="easy",
            title="第 6 周轻松跑",
            prescription={"distance_m": 8000, "pace": "5:50-6:10"},
        )
    )
    session.add(
        PlannedSessionRow(
            id=new_id(),
            plan_id=plan_id,
            scheduled_date=date(2026, 8, 31),
            session_type="tempo",
            title="第 6 周节奏跑",
            prescription={"distance_m": 10000, "pace": "5:10"},
        )
    )

    session.add(
        AthleteStateSnapshotRow(
            id=new_id(),
            user_id=user_id,
            version=1,
            as_of=datetime(2026, 8, 27, 23, 59, tzinfo=timezone.utc),
            fatigue_level="moderate",
            recovery_level="fair",
            recent_training_load=42.0,
            workout_completion_rate=0.85,
            confidence=0.7,
            algorithm_version="seed-fixture",
            created_at=now,
        )
    )
    await session.flush()
    return VerticalSliceSeed(
        user_id=user_id,
        goal_id=goal_id,
        plan_id=plan_id,
        workout_ids=tuple(workout_ids),
    )
