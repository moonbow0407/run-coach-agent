"""近期反馈摘要注入 WorkingContext，减少 get_workout_feedback 搜索跳转。"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.agent.context.providers import DomainWorkingContextProvider
from app.coaching.application.workout_service import (
    RECENT_FEEDBACK_SUMMARY_LIMIT,
    FeedbackSummary,
    WorkoutQueryService,
)
from app.coaching.domain.workout.models import Workout, WorkoutFeedback, WorkoutSource, WorkoutType
from app.common.clock import FrozenClock
from app.common.ids import new_id


class _FakeGoals:
    async def get_active_goal(self, *, user_id):
        return None


class _FakePlans:
    async def get_active_plan_summary(self, *, user_id, as_of):
        return None


class _FakeAthlete:
    async def get_latest_athlete_state(self, *, user_id):
        return None


class _FakeWorkoutRepo:
    def __init__(self, workouts, feedbacks):
        self._workouts = workouts
        self._feedbacks = feedbacks

    async def list_recent(self, *, user_id, since, limit):
        return [w for w in self._workouts if w.started_at >= since][:limit]

    async def list_feedback_for_workouts(self, *, user_id, workout_ids, end):
        ids = set(workout_ids)
        return [f for f in self._feedbacks if f.workout_id in ids and f.created_at <= end]

    async def get(self, *, user_id, workout_id):
        return None

    async def get_feedback(self, *, user_id, workout_id):
        return None

    async def list_between(self, *, user_id, start, end, limit):
        return []


@pytest.mark.asyncio
async def test_working_context_includes_recent_feedback_summaries() -> None:
    """验证：热上下文注入最近反馈的日期、RPE 与备注片段。"""
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    user_id = uuid4()
    w1 = Workout(
        id=new_id(),
        user_id=user_id,
        started_at=now - timedelta(days=1),
        distance_m=10000,
        duration_s=3600,
        avg_heart_rate=150,
        max_heart_rate=170,
        workout_type=WorkoutType.TEMPO,
        source=WorkoutSource.MANUAL,
        created_at=now,
        updated_at=now,
    )
    w2 = Workout(
        id=new_id(),
        user_id=user_id,
        started_at=now - timedelta(days=3),
        distance_m=8000,
        duration_s=3000,
        avg_heart_rate=140,
        max_heart_rate=160,
        workout_type=WorkoutType.EASY,
        source=WorkoutSource.MANUAL,
        created_at=now,
        updated_at=now,
    )
    long_note = "右膝外侧有点酸痛，下坡时更明显，需要观察。" + ("x" * 100)
    f1 = WorkoutFeedback(
        id=new_id(),
        user_id=user_id,
        workout_id=w1.id,
        perceived_exertion=8,
        subjective_fatigue=7,
        soreness=5,
        note=long_note,
        created_at=now,
        updated_at=now,
    )
    f2 = WorkoutFeedback(
        id=new_id(),
        user_id=user_id,
        workout_id=w2.id,
        perceived_exertion=4,
        subjective_fatigue=3,
        soreness=2,
        note="轻松",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    service = WorkoutQueryService(_FakeWorkoutRepo([w1, w2], [f1, f2]), FrozenClock(now))
    provider = DomainWorkingContextProvider(_FakeGoals(), _FakePlans(), _FakeAthlete(), service)
    working = await provider.load(user_id=user_id, as_of=now)
    assert len(working.recent_feedback) == 2
    assert working.recent_feedback[0].workout_id == w1.id
    assert working.recent_feedback[0].started_on == date(2026, 9, 7)
    assert working.recent_feedback[0].perceived_exertion == 8
    assert working.recent_feedback[0].note_snippet is not None
    assert working.recent_feedback[0].note_snippet.endswith("…")
    assert len(working.recent_feedback[0].note_snippet) <= 81


@pytest.mark.asyncio
async def test_feedback_summary_respects_limit() -> None:
    """验证：摘要条数不超过硬上限。"""
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    user_id = uuid4()
    workouts = []
    feedbacks = []
    for i in range(RECENT_FEEDBACK_SUMMARY_LIMIT + 3):
        wid = new_id()
        workouts.append(
            Workout(
                id=wid,
                user_id=user_id,
                started_at=now - timedelta(days=i),
                distance_m=5000,
                duration_s=1800,
                avg_heart_rate=130,
                max_heart_rate=150,
                workout_type=WorkoutType.EASY,
                source=WorkoutSource.MANUAL,
                created_at=now,
                updated_at=now,
            )
        )
        feedbacks.append(
            WorkoutFeedback(
                id=new_id(),
                user_id=user_id,
                workout_id=wid,
                perceived_exertion=5,
                subjective_fatigue=4,
                soreness=3,
                note=f"n{i}",
                created_at=now,
                updated_at=now,
            )
        )
    service = WorkoutQueryService(_FakeWorkoutRepo(workouts, feedbacks), FrozenClock(now))
    summaries = await service.list_recent_feedback_summaries(user_id=user_id)
    assert len(summaries) == RECENT_FEEDBACK_SUMMARY_LIMIT
    assert isinstance(summaries[0], FeedbackSummary)
