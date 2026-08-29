"""AthleteStateEvaluatorV1：疲劳 / 恢复 / 置信度 / 垂直切片输入。"""

from datetime import UTC, datetime, timedelta

from app.coaching.domain.analysis.training_load import analyze_training_load, session_rpe_load
from app.coaching.domain.athlete.evaluator import AthleteStateEvaluatorV1, AthleteStateEvidence
from app.coaching.domain.athlete.models import FatigueLevel, RecoveryLevel
from app.coaching.domain.workout.models import WorkoutType
from tests.unit.coaching_factories import make_feedback, make_workout

AS_OF = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


def _evaluate(workouts, feedbacks):
    analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=workouts,
        feedback_by_workout_id={item.workout_id: item for item in feedbacks},
    )
    return AthleteStateEvaluatorV1().evaluate(
        AthleteStateEvidence(
            as_of=AS_OF,
            recent_workouts=tuple(workouts),
            recent_feedback=tuple(feedbacks),
            training_load_analysis=analysis,
        )
    )


def test_high_fatigue_from_fatigue_8() -> None:
    workout = make_workout(
        started_at=AS_OF - timedelta(hours=10), workout_type=WorkoutType.EASY
    )
    feedback = make_feedback(
        workout_id=workout.id, subjective_fatigue=8, soreness=3, perceived_exertion=5
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.HIGH
    assert assessment.recovery_level is RecoveryLevel.POOR


def test_high_fatigue_from_fatigue_7_and_soreness_6() -> None:
    workout = make_workout(
        started_at=AS_OF - timedelta(hours=10), workout_type=WorkoutType.EASY
    )
    feedback = make_feedback(
        workout_id=workout.id, subjective_fatigue=7, soreness=6, perceived_exertion=5
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.HIGH
    assert assessment.recovery_level is RecoveryLevel.FAIR


def test_high_fatigue_from_fatigue_7_on_interval() -> None:
    workout = make_workout(
        started_at=AS_OF - timedelta(hours=10), workout_type=WorkoutType.INTERVAL
    )
    feedback = make_feedback(
        workout_id=workout.id, subjective_fatigue=7, soreness=3, perceived_exertion=5
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.HIGH


def test_high_rpe_alone_is_hard_session_not_high_fatigue() -> None:
    workout = make_workout(
        started_at=AS_OF - timedelta(hours=10), workout_type=WorkoutType.EASY
    )
    feedback = make_feedback(
        workout_id=workout.id, perceived_exertion=9, subjective_fatigue=3, soreness=3
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.LOW
    assert any(signal.code == "hard_session" for signal in assessment.signals)
    assert assessment.fatigue_level is not FatigueLevel.HIGH


def test_moderate_fatigue() -> None:
    workout = make_workout(started_at=AS_OF - timedelta(hours=10))
    feedback = make_feedback(
        workout_id=workout.id, subjective_fatigue=6, soreness=4, perceived_exertion=5
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.MODERATE
    assert assessment.recovery_level is RecoveryLevel.FAIR


def test_low_fatigue_and_good_recovery_without_recent_quality() -> None:
    workout = make_workout(
        started_at=AS_OF - timedelta(hours=30), workout_type=WorkoutType.EASY
    )
    feedback = make_feedback(
        workout_id=workout.id, subjective_fatigue=3, soreness=2, perceived_exertion=4
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.LOW
    assert assessment.recovery_level is RecoveryLevel.GOOD


def test_unknown_when_no_feedback() -> None:
    workout = make_workout(started_at=AS_OF - timedelta(hours=10))
    assessment = _evaluate([workout], [])
    assert assessment.fatigue_level is None
    assert assessment.recovery_level is None
    assert any(signal.code == "insufficient_recent_feedback" for signal in assessment.signals)


def test_feedback_created_after_as_of_is_ignored() -> None:
    """情况 A：as_of 之后才报告的反馈不允许污染历史快照。

    Workout 在 as_of 之前、反馈在 as_of 之后创建——若按 workout.started_at
    锚定 recency，这条未来反馈会被错误地计入。
    """
    workout = make_workout(
        started_at=AS_OF - timedelta(days=1), workout_type=WorkoutType.INTERVAL
    )
    future_feedback = make_feedback(
        workout_id=workout.id,
        subjective_fatigue=9,
        soreness=9,
        perceived_exertion=9,
        created_at=AS_OF + timedelta(days=2),
    )
    analysis = analyze_training_load(
        as_of=AS_OF,
        workouts=[workout],
        feedback_by_workout_id={},
    )
    assessment = AthleteStateEvaluatorV1().evaluate(
        AthleteStateEvidence(
            as_of=AS_OF,
            recent_workouts=(workout,),
            recent_feedback=(future_feedback,),
            training_load_analysis=analysis,
        )
    )
    assert assessment.fatigue_level is None
    assert assessment.recovery_level is None
    assert any(
        signal.code == "insufficient_recent_feedback" for signal in assessment.signals
    )


def test_late_reported_feedback_uses_created_at_for_recency() -> None:
    """情况 B：训练发生在 4 天前、反馈今天才补报，仍属于"最近 72 小时反馈"。"""
    workout = make_workout(
        started_at=AS_OF - timedelta(days=4), workout_type=WorkoutType.EASY
    )
    feedback = make_feedback(
        workout_id=workout.id,
        subjective_fatigue=6,
        soreness=6,
        perceived_exertion=5,
        created_at=AS_OF - timedelta(hours=1),
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.fatigue_level is FatigueLevel.MODERATE
    assert assessment.recovery_level is RecoveryLevel.FAIR
    assert any(
        signal.code == "moderate_subjective_fatigue" for signal in assessment.signals
    )


def test_quality_session_does_not_force_poor_recovery() -> None:
    workout = make_workout(
        started_at=AS_OF - timedelta(hours=10), workout_type=WorkoutType.INTERVAL
    )
    feedback = make_feedback(
        workout_id=workout.id, subjective_fatigue=3, soreness=2, perceived_exertion=5
    )
    assessment = _evaluate([workout], [feedback])
    assert assessment.recovery_level is not RecoveryLevel.POOR
    assert any(signal.code == "recent_quality_session" for signal in assessment.signals)


def test_load_change_cannot_push_unknown_to_high() -> None:
    heavy = make_workout(started_at=AS_OF - timedelta(days=1), duration_s=7200)
    prev = make_workout(started_at=AS_OF - timedelta(days=10), duration_s=1800)
    f1 = make_feedback(workout_id=heavy.id, perceived_exertion=9)
    f2 = make_feedback(workout_id=prev.id, perceived_exertion=5)
    assessment = _evaluate([heavy, prev], [f1, f2])
    assert assessment.fatigue_level is None
    assert any(signal.code == "hard_session" for signal in assessment.signals)


def test_confidence_formula() -> None:
    workouts = [
        make_workout(started_at=AS_OF - timedelta(days=d)) for d in (1, 2, 3)
    ]
    feedback = make_feedback(
        workout_id=workouts[0].id, subjective_fatigue=3, soreness=3, perceived_exertion=5
    )
    feedbacks = [feedback] + [
        make_feedback(workout_id=item.id, perceived_exertion=5) for item in workouts[1:]
    ]
    assessment = _evaluate(workouts, feedbacks)
    # 0.20 基础 + 0.40 有 72h 反馈 + 0.20 十四天至少 3 次 + 0.20 coverage>=0.5
    assert assessment.confidence == 1.0


def test_workout_completion_rate_always_none() -> None:
    workout = make_workout(started_at=AS_OF - timedelta(hours=10))
    assessment = _evaluate([workout], [])
    assert assessment.workout_completion_rate is None


def test_seed_vertical_slice_inputs_high_fair() -> None:
    user = make_workout(started_at=AS_OF).user_id
    easy = make_workout(
        started_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
        duration_s=2880,
        distance_m=8000,
        workout_type=WorkoutType.EASY,
        user_id=user,
        avg_heart_rate=142,
        max_heart_rate=158,
    )
    tempo = make_workout(
        started_at=datetime(2026, 8, 22, 6, 0, tzinfo=UTC),
        duration_s=3000,
        distance_m=10000,
        workout_type=WorkoutType.TEMPO,
        user_id=user,
        avg_heart_rate=158,
        max_heart_rate=172,
    )
    long_run = make_workout(
        started_at=datetime(2026, 8, 24, 6, 0, tzinfo=UTC),
        duration_s=6600,
        distance_m=18000,
        workout_type=WorkoutType.LONG_RUN,
        user_id=user,
        avg_heart_rate=148,
        max_heart_rate=165,
    )
    interval = make_workout(
        started_at=datetime(2026, 8, 27, 6, 0, tzinfo=UTC),
        duration_s=2520,
        distance_m=8000,
        workout_type=WorkoutType.INTERVAL,
        user_id=user,
        avg_heart_rate=168,
        max_heart_rate=181,
    )
    feedback = make_feedback(
        workout_id=interval.id,
        user_id=user,
        perceived_exertion=8,
        subjective_fatigue=7,
        soreness=6,
        note="最后两组间歇明显掉速",
        created_at=datetime(2026, 8, 27, 8, 0, tzinfo=UTC),
    )
    assessment = _evaluate([easy, tempo, long_run, interval], [feedback])
    assert assessment.fatigue_level is FatigueLevel.HIGH
    assert assessment.recovery_level is RecoveryLevel.FAIR
    assert assessment.algorithm_version == "phase3.v1"
    assert assessment.workout_completion_rate is None
    assert assessment.training_load_coverage is not None
    assert assessment.training_load_coverage < 0.5
    assert assessment.recent_training_load is None
    assert session_rpe_load(duration_s=2520, perceived_exertion=8) == 42.0 * 8
    codes = {signal.code for signal in assessment.signals}
    assert "low_training_load_coverage" in codes
    assert "hard_session" in codes
