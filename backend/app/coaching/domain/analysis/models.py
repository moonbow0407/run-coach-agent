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

    start: datetime  # 窗口起点（含）
    end: datetime  # 窗口终点（含）
    workout_count: int  # 窗口内训练课次总数
    total_duration_s: int  # 有时长记录课次的时长合计（秒）
    total_distance_m: float  # 有距离记录课次的距离合计（米）
    quality_session_count: int  # 质量课（节奏 / 间歇 / 比赛）数量
    srpe_load_sum: float | None  # 覆盖完整时的 sRPE 负荷合计；否则 None
    partial_srpe_load: float | None  # 覆盖不完整时的部分负荷合计；完整时为 None
    srpe_eligible_count: int  # 有负荷计算资格的课次（有时长记录）
    srpe_available_count: int  # 真正算出负荷的课次（时长 + RPE 齐备）
    srpe_coverage: float | None  # 覆盖率 = available / eligible；无资格课次为 None
    is_partial: bool  # 是否存在部分覆盖（0 < 覆盖率 < 1）

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

    as_of: datetime  # 分析基准时间：窗口切分与"排除未来证据"的锚点
    current: TrainingLoadWindow  # 最近 7 日窗
    previous: TrainingLoadWindow  # 之前的 7 日窗（对照组）
    load_change_ratio: float | None  # 当前窗 / 前窗可用负荷之比；不可比时为 None
    load_change_unavailable_reason: str | None  # 比值不可用的机器可读原因码


@dataclass(frozen=True)
class WorkoutAnalysis:
    """单次训练的确定性分析。same_day_planned_sessions 只是同日计划上下文。"""

    workout: Workout  # 被分析的训练记录
    feedback: WorkoutFeedback | None  # as_of 时点最新一条用户反馈
    session_rpe_load: float | None  # 该课的 sRPE 负荷；缺时长或 RPE 为 None
    quality_session: bool  # 是否质量课（节奏 / 间歇 / 比赛）
    same_day_planned_sessions: tuple[PlannedSession, ...]  # 同日计划课次，仅上下文
