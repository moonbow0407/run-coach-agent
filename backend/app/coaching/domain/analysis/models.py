"""训练分析的派生指标。只描述已发生的事实，不修改 Workout / Plan / State。"""

from dataclasses import dataclass
from datetime import datetime

from app.coaching.domain.plan.models import PlannedSession
from app.coaching.domain.workout.models import Workout, WorkoutFeedback, WorkoutType

# Phase 3 v1 的工程 Evidence Coverage 门槛，不是运动科学阈值。
SRPE_COVERAGE_THRESHOLD = 0.5
CURRENT_WINDOW_DAYS = 7
PREVIOUS_WINDOW_DAYS = 7

# 质量课只用于 category / signal，不作为 session-RPE 的替代系数。
QUALITY_WORKOUT_TYPES = frozenset(
    {WorkoutType.TEMPO, WorkoutType.INTERVAL, WorkoutType.RACE}
)


@dataclass(frozen=True)
class TrainingLoadWindow:
    """一个固定时间窗的训练量与 sRPE 覆盖情况。"""

    start: datetime
    end: datetime
    workout_count: int
    total_duration_s: int
    total_distance_m: float
    quality_session_count: int
    srpe_load_sum: float | None
    partial_srpe_load: float | None
    srpe_eligible_count: int
    srpe_available_count: int
    srpe_coverage: float | None
    is_partial: bool

    def usable_srpe_load(self) -> float | None:
        """coverage >= 门槛时返回窗口 sRPE 合计；否则 None。"""
        if self.srpe_coverage is None or self.srpe_coverage < SRPE_COVERAGE_THRESHOLD:
            return None
        if self.srpe_load_sum is not None:
            return self.srpe_load_sum
        return self.partial_srpe_load


@dataclass(frozen=True)
class TrainingLoadAnalysis:
    """当前 7 日窗与前一个 7 日窗的确定性训练负荷分析。"""

    as_of: datetime
    current: TrainingLoadWindow
    previous: TrainingLoadWindow
    load_change_ratio: float | None
    load_change_unavailable_reason: str | None


@dataclass(frozen=True)
class WorkoutAnalysis:
    """单次训练的确定性分析。same_day_planned_sessions 只是同日计划上下文。"""

    workout: Workout
    feedback: WorkoutFeedback | None
    session_rpe_load: float | None
    quality_session: bool
    same_day_planned_sessions: tuple[PlannedSession, ...]
