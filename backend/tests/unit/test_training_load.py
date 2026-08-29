"""Training Analysis 纯领域测试：调用正式函数，不另写第二套算法。"""

from datetime import UTC, datetime, timedelta

from app.coaching.domain.analysis.training_load import (
    analyze_training_load,
    session_rpe_load,
)
from app.coaching.domain.workout.models import WorkoutType
from tests.unit.coaching_factories import make_feedback, make_workout

AS_OF = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


def test_session_rpe_is_duration_minutes_times_rpe() -> None:
    assert session_rpe_load(duration_s=2520, perceived_exertion=8) == (2520 / 60.0) * 8
    assert session_rpe_load(duration_s=3600, perceived_exertion=5) == 60.0 * 5


def test_missing_rpe_or_duration_is_not_imputed() -> None:
    assert session_rpe_load(duration_s=3600, perceived_exertion=None) is None
    assert session_rpe_load(duration_s=None, perceived_exertion=8) is None
    assert session_rpe_load(duration_s=None, perceived_exertion=None) is None


def test_workout_type_is_not_a_load_factor() -> None:
    easy = make_workout(started_at=AS_OF - timedelta(days=1), workout_type=WorkoutType.EASY)
    interval = make_workout(
        started_at=AS_OF - timedelta(days=1),
        workout_type=WorkoutType.INTERVAL,
        workout_id=easy.id,
        user_id=easy.user_id,
        duration_s=easy.duration_s,
    )
    feedback = make_feedback(workout_id=easy.id, perceived_exertion=7)
    easy_analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=[easy],
        feedback_by_workout_id={easy.id: feedback},
    )
    interval_analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=[interval],
        feedback_by_workout_id={interval.id: feedback},
    )
    assert easy_analysis.current.srpe_load_sum == interval_analysis.current.srpe_load_sum
    assert easy_analysis.current.quality_session_count == 0
    assert interval_analysis.current.quality_session_count == 1


def test_future_workouts_are_excluded() -> None:
    past = make_workout(started_at=AS_OF - timedelta(days=1), duration_s=1800)
    future = make_workout(started_at=AS_OF + timedelta(hours=2), duration_s=3600)
    analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=[past, future],
        feedback_by_workout_id={},
    )
    assert analysis.current.workout_count == 1
    assert analysis.current.total_duration_s == 1800


def test_coverage_partial_and_complete() -> None:
    w1 = make_workout(started_at=AS_OF - timedelta(days=1), duration_s=1800)
    w2 = make_workout(started_at=AS_OF - timedelta(days=2), duration_s=1800)
    feedback = make_feedback(workout_id=w1.id, perceived_exertion=5)
    partial = analyze_training_load(
        as_of=AS_OF,
        workouts=[w1, w2],
        feedback_by_workout_id={w1.id: feedback},
    )
    assert partial.current.srpe_eligible_count == 2
    assert partial.current.srpe_available_count == 1
    assert partial.current.srpe_coverage == 0.5
    assert partial.current.is_partial is True
    assert partial.current.srpe_load_sum is None
    assert partial.current.partial_srpe_load == session_rpe_load(
        duration_s=1800, perceived_exertion=5
    )

    f2 = make_feedback(workout_id=w2.id, perceived_exertion=5)
    complete = analyze_training_load(
        as_of=AS_OF,
        workouts=[w1, w2],
        feedback_by_workout_id={w1.id: feedback, w2.id: f2},
    )
    assert complete.current.is_partial is False
    assert complete.current.srpe_coverage == 1.0
    assert complete.current.partial_srpe_load is None
    assert complete.current.srpe_load_sum == 2 * session_rpe_load(
        duration_s=1800, perceived_exertion=5
    )


def test_coverage_none_when_no_eligible_workouts() -> None:
    rest = make_workout(
        started_at=AS_OF - timedelta(days=1),
        duration_s=None,
        distance_m=None,
        workout_type=WorkoutType.OTHER,
    )
    analysis = analyze_training_load(as_of=AS_OF, workouts=[rest], feedback_by_workout_id={})
    assert analysis.current.srpe_coverage is None
    assert analysis.current.is_partial is False


def test_windows_are_current_7d_and_previous_7d() -> None:
    current_w = make_workout(started_at=AS_OF - timedelta(days=2))
    previous_w = make_workout(started_at=AS_OF - timedelta(days=10))
    older = make_workout(started_at=AS_OF - timedelta(days=20))
    boundary = make_workout(started_at=AS_OF - timedelta(days=7))
    analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=[current_w, previous_w, older, boundary],
        feedback_by_workout_id={},
    )
    assert analysis.current.workout_count == 2  # current + 7 日边界归入当前窗
    assert analysis.previous.workout_count == 1
    assert older.started_at < analysis.previous.start


def test_load_change_ratio_reasons() -> None:
    w_now = make_workout(started_at=AS_OF - timedelta(days=1), duration_s=1800)
    analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=[w_now],
        feedback_by_workout_id={},
    )
    assert analysis.load_change_ratio is None
    assert analysis.load_change_unavailable_reason == "insufficient_current_coverage"

    f_now = make_feedback(workout_id=w_now.id, perceived_exertion=5)
    only_current = analyze_training_load(
        as_of=AS_OF,
        workouts=[w_now],
        feedback_by_workout_id={w_now.id: f_now},
    )
    assert only_current.current.srpe_coverage == 1.0
    assert only_current.load_change_ratio is None
    assert only_current.load_change_unavailable_reason == "insufficient_previous_coverage"

    w_prev = make_workout(started_at=AS_OF - timedelta(days=10), duration_s=1800)
    f_prev = make_feedback(workout_id=w_prev.id, perceived_exertion=5)
    both = analyze_training_load(
        as_of=AS_OF,
        workouts=[w_now, w_prev],
        feedback_by_workout_id={w_now.id: f_now, w_prev.id: f_prev},
    )
    assert both.load_change_ratio == 1.0
    assert both.load_change_unavailable_reason is None


async def test_analysis_service_does_not_call_get_feedback_per_workout() -> None:
    """N+1 防护：应用服务只走批量 Feedback 查询。"""
    from app.coaching.application.training_analysis_service import TrainingAnalysisService

    class FakeWorkouts:
        def __init__(self) -> None:
            self.get_feedback_calls = 0
            self.batch_calls = 0
            self.workouts = [
                make_workout(started_at=AS_OF - timedelta(days=1)),
                make_workout(started_at=AS_OF - timedelta(days=2)),
            ]

        async def list_between(self, *, user_id, start, end, limit):
            return self.workouts

        async def get_feedback(self, *, user_id, workout_id):
            self.get_feedback_calls += 1

        async def list_feedback_for_workouts(self, *, user_id, workout_ids):
            self.batch_calls += 1
            return []

        async def get(self, *, user_id, workout_id):
            return None

        async def list_recent(self, *, user_id, since, limit):
            return []

    class FakePlans:
        async def get_active(self, *, user_id):
            return None

        async def get(self, *, user_id, plan_id):
            return None

        async def list_sessions(self, *, user_id, plan_id):
            return []

    fake = FakeWorkouts()
    service = TrainingAnalysisService(fake, FakePlans())
    await service.analyze_training_load(user_id=fake.workouts[0].user_id, as_of=AS_OF)
    assert fake.get_feedback_calls == 0
    assert fake.batch_calls == 1
