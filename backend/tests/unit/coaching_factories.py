"""单元测试用的 Workout / Feedback 构造，避免每个测试复制样板。"""

from datetime import UTC, datetime
from uuid import uuid4

from app.coaching.domain.workout.models import (
    Workout,
    WorkoutFeedback,
    WorkoutSource,
    WorkoutType,
)


def make_workout(
    *,
    started_at: datetime,
    duration_s: int | None = 3600,
    distance_m: float | None = 8000.0,
    workout_type: WorkoutType = WorkoutType.EASY,
    workout_id=None,
    user_id=None,
    avg_heart_rate: int | None = 140,
    max_heart_rate: int | None = 160,
) -> Workout:
    now = started_at
    return Workout(
        id=workout_id or uuid4(),
        user_id=user_id or uuid4(),
        started_at=started_at,
        distance_m=distance_m,
        duration_s=duration_s,
        avg_heart_rate=avg_heart_rate,
        max_heart_rate=max_heart_rate,
        workout_type=workout_type,
        source=WorkoutSource.MANUAL,
        created_at=now,
    )


def make_feedback(
    *,
    workout_id,
    user_id=None,
    perceived_exertion: int | None = None,
    subjective_fatigue: int | None = None,
    soreness: int | None = None,
    note: str | None = None,
    created_at: datetime | None = None,
) -> WorkoutFeedback:
    return WorkoutFeedback(
        id=uuid4(),
        user_id=user_id or uuid4(),
        workout_id=workout_id,
        perceived_exertion=perceived_exertion,
        subjective_fatigue=subjective_fatigue,
        soreness=soreness,
        note=note,
        created_at=created_at or datetime(2026, 8, 27, 8, 0, tzinfo=UTC),
    )
