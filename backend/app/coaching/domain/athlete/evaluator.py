"""AthleteStateEvaluatorV1：纯领域逻辑，不依赖仓储、时钟或 LLM。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.coaching.domain.analysis.models import TrainingLoadAnalysis
from app.coaching.domain.analysis.training_load import is_quality_workout
from app.coaching.domain.athlete.models import (
    ALGORITHM_VERSION_V1,
    FatigueLevel,
    RecoveryLevel,
)
from app.coaching.domain.athlete.signals import AthleteStateSignal
from app.coaching.domain.workout.models import Workout, WorkoutFeedback, WorkoutType

_FATIGUE_LOOKBACK = timedelta(hours=72)
_QUALITY_LOOKBACK = timedelta(hours=24)
_WORKOUT_LOOKBACK = timedelta(days=14)
_MIN_WORKOUTS_FOR_CONFIDENCE = 3
_HIGH_INTENSITY_TYPES = frozenset(
    {WorkoutType.TEMPO, WorkoutType.INTERVAL, WorkoutType.RACE}
)


@dataclass(frozen=True)
class AthleteStateEvidence:
    """Evaluator 的输入。Phase 3 不把计划完成率塞进 Evidence。"""

    as_of: datetime
    recent_workouts: tuple[Workout, ...]
    recent_feedback: tuple[WorkoutFeedback, ...]
    training_load_analysis: TrainingLoadAnalysis


@dataclass(frozen=True)
class AthleteStateAssessment:
    """Evaluator 输出。Application 再把它写成 Snapshot。"""

    fatigue_level: FatigueLevel | None
    recovery_level: RecoveryLevel | None
    recent_training_load: float | None
    workout_completion_rate: None
    training_load_coverage: float | None
    confidence: float
    algorithm_version: str
    signals: tuple[AthleteStateSignal, ...]


class AthleteStateEvaluatorV1:
    """algorithm_version = phase3.v1。只读 Evidence，不做 I/O。"""

    algorithm_version = ALGORITHM_VERSION_V1

    def evaluate(self, evidence: AthleteStateEvidence) -> AthleteStateAssessment:
        as_of = evidence.as_of
        workouts = tuple(
            workout for workout in evidence.recent_workouts if workout.started_at <= as_of
        )
        workouts_by_id = {workout.id: workout for workout in workouts}
        feedback_72h = _feedback_in_window(
            evidence.recent_feedback,
            workouts_by_id,
            start=as_of - _FATIGUE_LOOKBACK,
            as_of=as_of,
        )
        fatigue = _fatigue_level(feedback_72h, workouts_by_id)
        recovery = _recovery_level(feedback_72h, workouts, as_of)
        coverage = evidence.training_load_analysis.current.srpe_coverage
        recent_load = evidence.training_load_analysis.current.usable_srpe_load()
        signals = _signals(
            as_of=as_of,
            feedback_72h=feedback_72h,
            workouts=workouts,
            analysis=evidence.training_load_analysis,
            coverage=coverage,
        )
        return AthleteStateAssessment(
            fatigue_level=fatigue,
            recovery_level=recovery,
            recent_training_load=recent_load,
            workout_completion_rate=None,
            training_load_coverage=coverage,
            confidence=_confidence(as_of, feedback_72h, workouts, coverage),
            algorithm_version=self.algorithm_version,
            signals=signals,
        )


def _feedback_in_window(
    feedbacks: Sequence[WorkoutFeedback],
    workouts_by_id: dict,
    *,
    start: datetime,
    as_of: datetime,
) -> tuple[WorkoutFeedback, ...]:
    matched: list[WorkoutFeedback] = []
    for feedback in feedbacks:
        workout = workouts_by_id.get(feedback.workout_id)
        evidence_time = workout.started_at if workout is not None else feedback.created_at
        if start <= evidence_time <= as_of:
            matched.append(feedback)
    return tuple(matched)


def _fatigue_level(
    feedback_72h: Sequence[WorkoutFeedback],
    workouts_by_id: dict,
) -> FatigueLevel | None:
    if any(_is_high_fatigue(item, workouts_by_id) for item in feedback_72h):
        return FatigueLevel.HIGH
    if any(_is_moderate_fatigue(item) for item in feedback_72h):
        return FatigueLevel.MODERATE
    explicit_low = [item for item in feedback_72h if _is_explicit_low(item)]
    if explicit_low and len(explicit_low) == len(feedback_72h):
        return FatigueLevel.LOW
    return None


def _is_high_fatigue(feedback: WorkoutFeedback, workouts_by_id: dict) -> bool:
    fatigue = feedback.subjective_fatigue
    soreness = feedback.soreness
    if fatigue is not None and fatigue >= 8:
        return True
    if soreness is not None and soreness >= 8:
        return True
    if fatigue is not None and fatigue >= 7 and soreness is not None and soreness >= 6:
        return True
    workout = workouts_by_id.get(feedback.workout_id)
    return (
        fatigue is not None
        and fatigue >= 7
        and workout is not None
        and workout.workout_type in _HIGH_INTENSITY_TYPES
    )


def _is_moderate_fatigue(feedback: WorkoutFeedback) -> bool:
    fatigue = feedback.subjective_fatigue
    soreness = feedback.soreness
    return (fatigue is not None and fatigue >= 6) or (
        soreness is not None and soreness >= 6
    )


def _is_explicit_low(feedback: WorkoutFeedback) -> bool:
    fatigue = feedback.subjective_fatigue
    soreness = feedback.soreness
    return (
        fatigue is not None
        and soreness is not None
        and fatigue <= 4
        and soreness <= 4
    )


def _recovery_level(
    feedback_72h: Sequence[WorkoutFeedback],
    workouts: Sequence[Workout],
    as_of: datetime,
) -> RecoveryLevel | None:
    if any(
        (item.subjective_fatigue is not None and item.subjective_fatigue >= 8)
        or (item.soreness is not None and item.soreness >= 8)
        for item in feedback_72h
    ):
        return RecoveryLevel.POOR
    if any(
        (item.subjective_fatigue is not None and item.subjective_fatigue >= 6)
        or (item.soreness is not None and item.soreness >= 6)
        for item in feedback_72h
    ):
        return RecoveryLevel.FAIR
    explicit_low = [item for item in feedback_72h if _is_explicit_low(item)]
    if explicit_low and len(explicit_low) == len(feedback_72h):
        quality_start = as_of - _QUALITY_LOOKBACK
        has_recent_quality = any(
            is_quality_workout(workout.workout_type)
            and quality_start <= workout.started_at <= as_of
            for workout in workouts
        )
        if not has_recent_quality:
            return RecoveryLevel.GOOD
    return None


def _confidence(
    as_of: datetime,
    feedback_72h: Sequence[WorkoutFeedback],
    workouts: Sequence[Workout],
    coverage: float | None,
) -> float:
    value = 0.20
    if feedback_72h:
        value += 0.40
    lookback_start = as_of - _WORKOUT_LOOKBACK
    recent_count = sum(
        1 for workout in workouts if lookback_start <= workout.started_at <= as_of
    )
    if recent_count >= _MIN_WORKOUTS_FOR_CONFIDENCE:
        value += 0.20
    if coverage is not None and coverage >= 0.5:
        value += 0.20
    return min(1.0, max(0.20, value))


def _signals(
    *,
    as_of: datetime,
    feedback_72h: Sequence[WorkoutFeedback],
    workouts: Sequence[Workout],
    analysis: TrainingLoadAnalysis,
    coverage: float | None,
) -> tuple[AthleteStateSignal, ...]:
    signals: list[AthleteStateSignal] = []
    quality_start = as_of - _FATIGUE_LOOKBACK
    for feedback in feedback_72h:
        refs = _feedback_refs(feedback)
        if feedback.subjective_fatigue is not None and feedback.subjective_fatigue >= 8:
            signals.append(
                AthleteStateSignal(
                    code="high_subjective_fatigue",
                    severity="high",
                    message="最近 72 小时报告了很高的主观疲劳。",
                    evidence_refs=refs,
                )
            )
        elif feedback.subjective_fatigue is not None and feedback.subjective_fatigue >= 6:
            signals.append(
                AthleteStateSignal(
                    code="moderate_subjective_fatigue",
                    severity="moderate",
                    message="最近 72 小时报告了中等主观疲劳。",
                    evidence_refs=refs,
                )
            )
        if feedback.soreness is not None and feedback.soreness >= 8:
            signals.append(
                AthleteStateSignal(
                    code="high_soreness",
                    severity="high",
                    message="最近 72 小时报告了很高的酸痛。",
                    evidence_refs=refs,
                )
            )
        if feedback.perceived_exertion is not None and feedback.perceived_exertion >= 8:
            signals.append(
                AthleteStateSignal(
                    code="hard_session",
                    severity="info",
                    message="最近存在高 RPE 课次；高 RPE 本身不单独推出 HIGH 疲劳。",
                    evidence_refs=refs,
                )
            )
    quality_workouts = [
        workout
        for workout in workouts
        if is_quality_workout(workout.workout_type)
        and quality_start <= workout.started_at <= as_of
    ]
    if quality_workouts:
        signals.append(
            AthleteStateSignal(
                code="recent_quality_session",
                severity="info",
                message="最近 72 小时存在质量课（节奏 / 间歇 / 比赛）。",
                evidence_refs=tuple(f"workout:{item.id}" for item in quality_workouts),
            )
        )
    if coverage is None or coverage < 0.5:
        signals.append(
            AthleteStateSignal(
                code="low_training_load_coverage",
                severity="warning",
                message="近期 sRPE 覆盖不足，不能把部分负荷当成完整训练负荷。",
                evidence_refs=("training_load:current",),
            )
        )
    ratio = analysis.load_change_ratio
    if ratio is not None and ratio > 1.0:
        signals.append(
            AthleteStateSignal(
                code="recent_load_increase",
                severity="warning",
                message="近期训练负荷相对前一窗口上升。这是描述性趋势，不是伤病风险。",
                evidence_refs=("training_load:current", "training_load:previous"),
            )
        )
    if not feedback_72h:
        signals.append(
            AthleteStateSignal(
                code="insufficient_recent_feedback",
                severity="warning",
                message="最近 72 小时缺少主观反馈，疲劳与恢复无法确定。",
                evidence_refs=(),
            )
        )
    # 去重：同一 code 只保留第一次出现，避免多条 Feedback 重复堆叠。
    seen: set[str] = set()
    unique: list[AthleteStateSignal] = []
    for signal in signals:
        if signal.code in seen:
            continue
        seen.add(signal.code)
        unique.append(signal)
    return tuple(unique)


def _feedback_refs(feedback: WorkoutFeedback) -> tuple[str, ...]:
    return (f"feedback:{feedback.id}", f"workout:{feedback.workout_id}")
