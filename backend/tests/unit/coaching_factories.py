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
    started_at: datetime,  # 开课时间（必填，用于锚定时间窗）
    duration_s: int | None = 3600,  # 时长秒，默认 1 小时
    distance_m: float | None = 8000.0,  # 距离米，默认 8 公里
    workout_type: WorkoutType = WorkoutType.EASY,  # 课型，默认轻松跑
    workout_id=None,
    user_id=None,
    avg_heart_rate: int | None = 140,  # 平均心率（bpm）
    max_heart_rate: int | None = 160,  # 最大心率（bpm）
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
        updated_at=now,
    )


def make_feedback(
    *,
    workout_id,
    user_id=None,
    perceived_exertion: int | None = None,  # sRPE：主观用力程度（1-10）
    subjective_fatigue: int | None = None,  # 主观疲劳（1-10）
    soreness: int | None = None,  # 酸痛程度（1-10）
    note: str | None = None,  # 用户文字备注
    created_at: datetime | None = None,  # 反馈创建时间：决定是否计入 as_of 前的窗口
) -> WorkoutFeedback:
    moment = created_at or datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
    return WorkoutFeedback(
        id=uuid4(),
        user_id=user_id or uuid4(),
        workout_id=workout_id,
        perceived_exertion=perceived_exertion,
        subjective_fatigue=subjective_fatigue,
        soreness=soreness,
        note=note,
        created_at=moment,
        updated_at=moment,
    )
