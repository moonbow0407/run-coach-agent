"""计划调整领域生成：reduce_upcoming_load 与 convert_hard_sessions_to_easy。

模型不能提供课次 diff 或新处方；窗口与 TEMPO/INTERVAL 目标课型由本模块生成。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.coaching.domain.athlete.models import FatigueLevel, RecoveryLevel
from app.coaching.domain.plan.models import (
    PlanChangePayload,
    PlanChangeType,
    PlannedSession,
    SessionChange,
    SessionType,
)
from app.common.errors import DomainError

# 窗口边界：当天不可调整（从明天起算），最长 7 天防止一次性改动过多。
MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 7
# 可降级 / 转轻松跑的高强度课型；比赛课永不进入此集合。
HARD_SESSION_TYPES = frozenset({SessionType.TEMPO, SessionType.INTERVAL})


def rest_replacement_title(old_title: str) -> str:
    """TEMPO/INTERVAL→REST 的确定性标题；生成与激活校验共用同一格式。"""
    return f"恢复休息（调整自：{old_title}）"


def easy_replacement_title(old_title: str) -> str:
    """TEMPO/INTERVAL→EASY 的确定性标题；生成与激活校验共用同一格式。"""
    return f"轻松跑（调整自：{old_title}）"


def easy_replacement_prescription(old_prescription: dict[str, Any]) -> dict[str, Any]:
    """转轻松跑的确定性处方：只保留距离意图，去掉强度目标。"""
    prescription: dict[str, Any] = {"intent": "easy"}
    distance_km = old_prescription.get("distance_km")
    if isinstance(distance_km, (int, float)):
        prescription["distance_km"] = distance_km
    return prescription


def ensure_v1_reduction_precondition(
    fatigue_level: FatigueLevel | None,
    recovery_level: RecoveryLevel | None,
) -> None:
    """自动调整只允许在最保守的前提下降负荷；Proposal 与 Activation 共用。"""
    if fatigue_level != FatigueLevel.HIGH and recovery_level != RecoveryLevel.POOR:
        # 两者都不满足说明状态未恶化到需要干预，拒绝自动调整。
        raise DomainError("state_does_not_require_v1_reduction")


@dataclass(frozen=True)
class ReduceUpcomingLoadResult:
    """领域生成的降负荷 payload，以及 Observation 需要的 Race 提示。"""

    payload: PlanChangePayload  # 领域生成的课次替换 diff
    window_start: date  # 调整窗口起点（as_of 次日）
    window_end: date  # 调整窗口终点
    race_session_not_modified: bool  # 窗口内含 Race 课时为 True：仅提示，绝不改动
    change_type: PlanChangeType = PlanChangeType.REDUCE_UPCOMING_LOAD


@dataclass(frozen=True)
class ConvertHardSessionsToEasyResult:
    """领域生成的「高强度→轻松跑」payload，以及 Race 提示。"""

    payload: PlanChangePayload
    window_start: date
    window_end: date
    race_session_not_modified: bool
    change_type: PlanChangeType = PlanChangeType.CONVERT_HARD_SESSIONS_TO_EASY


def adaptation_window(*, as_of: datetime, horizon_days: int) -> tuple[date, date]:
    """作用窗口 [as_of.date+1, as_of.date+horizon_days]，不含当天与过去。"""
    return as_of.date() + timedelta(days=1), as_of.date() + timedelta(days=horizon_days)


def _sessions_in_window(
    *,
    as_of: datetime,
    horizon_days: int,
    sessions: Sequence[PlannedSession],
) -> tuple[date, date, list[PlannedSession], bool]:
    """校验 horizon、切窗口，并标记窗口内是否含比赛课。"""
    if not MIN_HORIZON_DAYS <= horizon_days <= MAX_HORIZON_DAYS:
        raise DomainError("horizon_days_out_of_range")
    window_start, window_end = adaptation_window(as_of=as_of, horizon_days=horizon_days)
    in_window = [
        session for session in sessions if window_start <= session.scheduled_date <= window_end
    ]
    race_in_window = any(session.session_type == SessionType.RACE for session in in_window)
    return window_start, window_end, in_window, race_in_window


def generate_reduce_upcoming_load(
    *,
    as_of: datetime,
    horizon_days: int,
    sessions: Sequence[PlannedSession],
    fatigue_level: FatigueLevel | None,
    recovery_level: RecoveryLevel | None,
) -> ReduceUpcomingLoadResult:
    ensure_v1_reduction_precondition(fatigue_level, recovery_level)
    window_start, window_end, in_window, race_in_window = _sessions_in_window(
        as_of=as_of, horizon_days=horizon_days, sessions=sessions
    )
    changes: list[SessionChange] = []
    for session in in_window:
        # 只把 TEMPO / INTERVAL 替换为休息，其余课次保持原样。
        if session.session_type not in HARD_SESSION_TYPES:
            continue
        changes.append(
            SessionChange(
                source_session_id=session.id,
                scheduled_date=session.scheduled_date,
                from_type=session.session_type,
                to_type=SessionType.REST,
                old_title=session.title,
                new_title=rest_replacement_title(session.title),
                old_prescription=dict(session.prescription),
                new_prescription={},
            )
        )
    if not changes:
        raise DomainError("no_applicable_sessions")
    return ReduceUpcomingLoadResult(
        payload=PlanChangePayload(horizon_days=horizon_days, changes=tuple(changes)),
        window_start=window_start,
        window_end=window_end,
        race_session_not_modified=race_in_window,
    )


def generate_convert_hard_sessions_to_easy(
    *,
    as_of: datetime,
    horizon_days: int,
    sessions: Sequence[PlannedSession],
    fatigue_level: FatigueLevel | None,
    recovery_level: RecoveryLevel | None,
) -> ConvertHardSessionsToEasyResult:
    """把窗口内 TEMPO/INTERVAL 改为同日轻松跑；不碰比赛课。"""
    ensure_v1_reduction_precondition(fatigue_level, recovery_level)
    window_start, window_end, in_window, race_in_window = _sessions_in_window(
        as_of=as_of, horizon_days=horizon_days, sessions=sessions
    )
    changes: list[SessionChange] = []
    for session in in_window:
        if session.session_type not in HARD_SESSION_TYPES:
            continue
        old_prescription = dict(session.prescription)
        changes.append(
            SessionChange(
                source_session_id=session.id,
                scheduled_date=session.scheduled_date,
                from_type=session.session_type,
                to_type=SessionType.EASY,
                old_title=session.title,
                new_title=easy_replacement_title(session.title),
                old_prescription=old_prescription,
                new_prescription=easy_replacement_prescription(old_prescription),
            )
        )
    if not changes:
        raise DomainError("no_applicable_sessions")
    return ConvertHardSessionsToEasyResult(
        payload=PlanChangePayload(horizon_days=horizon_days, changes=tuple(changes)),
        window_start=window_start,
        window_end=window_end,
        race_session_not_modified=race_in_window,
    )
