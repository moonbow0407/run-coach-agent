"""session-RPE 与训练负荷窗口的纯函数计算。

负荷只来自 duration × perceived_exertion；缺少 RPE 不补值，
workout_type 不作为生理负荷系数。
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from app.coaching.domain.analysis.models import (
    CURRENT_WINDOW_DAYS,
    PREVIOUS_WINDOW_DAYS,
    QUALITY_WORKOUT_TYPES,
    TrainingLoadAnalysis,
    TrainingLoadWindow,
)
from app.coaching.domain.workout.models import Workout, WorkoutFeedback, WorkoutType


def session_rpe_load(
    *,
    duration_s: int | None,
    perceived_exertion: int | None,
) -> float | None:
    """duration_minutes × perceived_exertion。任一缺失则无法计算。"""
    if duration_s is None or perceived_exertion is None:
        return None
    return (duration_s / 60.0) * perceived_exertion


def is_quality_workout(workout_type: WorkoutType) -> bool:
    """质量课信号：tempo / interval / race。不参与 sRPE 计算。"""
    return workout_type in QUALITY_WORKOUT_TYPES


def analyze_training_load(
    *,
    as_of: datetime,
    workouts: Sequence[Workout],
    feedback_by_workout_id: Mapping[UUID, WorkoutFeedback],
) -> TrainingLoadAnalysis:
    """按 as_of 切分当前 7 日窗与前一个 7 日窗。未来证据不进入计算。"""
    current_start = as_of - timedelta(days=CURRENT_WINDOW_DAYS)
    previous_start = as_of - timedelta(days=CURRENT_WINDOW_DAYS + PREVIOUS_WINDOW_DAYS)
    in_scope = [workout for workout in workouts if workout.started_at <= as_of]
    current = _window_metrics(
        start=current_start,
        end=as_of,
        workouts=[
            workout
            for workout in in_scope
            if current_start <= workout.started_at <= as_of
        ],
        feedback_by_workout_id=feedback_by_workout_id,
    )
    previous = _window_metrics(
        start=previous_start,
        end=current_start,
        workouts=[
            workout
            for workout in in_scope
            if previous_start <= workout.started_at < current_start
        ],
        feedback_by_workout_id=feedback_by_workout_id,
    )
    ratio, reason = _load_change_ratio(current, previous)
    return TrainingLoadAnalysis(
        as_of=as_of,
        current=current,
        previous=previous,
        load_change_ratio=ratio,
        load_change_unavailable_reason=reason,
    )


def _window_metrics(
    *,
    start: datetime,
    end: datetime,
    workouts: Sequence[Workout],
    feedback_by_workout_id: Mapping[UUID, WorkoutFeedback],
) -> TrainingLoadWindow:
    total_duration = 0
    total_distance = 0.0
    quality_count = 0
    eligible = 0
    available = 0
    load_sum = 0.0
    for workout in workouts:
        if workout.duration_s is not None:
            total_duration += workout.duration_s
            eligible += 1
        if workout.distance_m is not None:
            total_distance += workout.distance_m
        if is_quality_workout(workout.workout_type):
            quality_count += 1
        feedback = feedback_by_workout_id.get(workout.id)
        rpe = feedback.perceived_exertion if feedback is not None else None
        load = session_rpe_load(duration_s=workout.duration_s, perceived_exertion=rpe)
        if load is not None:
            available += 1
            load_sum += load

    coverage = (available / eligible) if eligible > 0 else None
    is_partial = coverage is not None and coverage < 1.0
    complete_sum: float | None
    partial_sum: float | None
    if coverage is None or available == 0:
        complete_sum = None
        partial_sum = None
    elif is_partial:
        complete_sum = None
        partial_sum = load_sum
    else:
        complete_sum = load_sum
        partial_sum = None
    return TrainingLoadWindow(
        start=start,
        end=end,
        workout_count=len(workouts),
        total_duration_s=total_duration,
        total_distance_m=total_distance,
        quality_session_count=quality_count,
        srpe_load_sum=complete_sum,
        partial_srpe_load=partial_sum,
        srpe_eligible_count=eligible,
        srpe_available_count=available,
        srpe_coverage=coverage,
        is_partial=is_partial,
    )


def _load_change_ratio(
    current: TrainingLoadWindow,
    previous: TrainingLoadWindow,
) -> tuple[float | None, str | None]:
    current_load = current.usable_srpe_load()
    previous_load = previous.usable_srpe_load()
    if current.srpe_coverage is None or current.srpe_coverage < 0.5:
        return None, "insufficient_current_coverage"
    if previous.srpe_coverage is None or previous.srpe_coverage < 0.5:
        return None, "insufficient_previous_coverage"
    if previous_load is None or previous_load <= 0:
        return None, "no_previous_baseline"
    if current_load is None:
        return None, "insufficient_current_coverage"
    return current_load / previous_load, None
