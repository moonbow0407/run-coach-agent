"""Phase 3 v1 唯一自动支持的计划调整：reduce_upcoming_load。

模型不能提供课次 diff 或新处方；窗口与 TEMPO/INTERVAL→REST 由本模块生成。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.coaching.domain.athlete.models import FatigueLevel, RecoveryLevel
from app.coaching.domain.plan.models import (
    PlanChangePayload,
    PlanChangeType,
    PlannedSession,
    SessionChange,
    SessionType,
)
from app.common.errors import DomainError

MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 7
REDUCIBLE_SESSION_TYPES = frozenset({SessionType.TEMPO, SessionType.INTERVAL})


def rest_replacement_title(old_title: str) -> str:
    """TEMPO/INTERVAL→REST 的确定性标题；生成与激活校验共用同一格式。"""
    return f"恢复休息（调整自：{old_title}）"


def ensure_v1_reduction_precondition(
    fatigue_level: FatigueLevel | None,
    recovery_level: RecoveryLevel | None,
) -> None:
    """v1 只允许在最保守的前提下降负荷；Proposal 与 Activation 共用同一判断。"""
    if fatigue_level != FatigueLevel.HIGH and recovery_level != RecoveryLevel.POOR:
        raise DomainError("state_does_not_require_v1_reduction")


@dataclass(frozen=True)
class ReduceUpcomingLoadResult:
    """领域生成的降负荷 payload，以及 Observation 需要的 Race 提示。"""

    payload: PlanChangePayload
    window_start: date
    window_end: date
    race_session_not_modified: bool
    change_type: PlanChangeType = PlanChangeType.REDUCE_UPCOMING_LOAD


def adaptation_window(*, as_of: datetime, horizon_days: int) -> tuple[date, date]:
    """作用窗口 [as_of.date+1, as_of.date+horizon_days]，不含当天与过去。"""
    return as_of.date() + timedelta(days=1), as_of.date() + timedelta(days=horizon_days)


def generate_reduce_upcoming_load(
    *,
    as_of: datetime,
    horizon_days: int,
    sessions: Sequence[PlannedSession],
    fatigue_level: FatigueLevel | None,
    recovery_level: RecoveryLevel | None,
) -> ReduceUpcomingLoadResult:
    if not MIN_HORIZON_DAYS <= horizon_days <= MAX_HORIZON_DAYS:
        raise DomainError("horizon_days_out_of_range")
    ensure_v1_reduction_precondition(fatigue_level, recovery_level)

    window_start, window_end = adaptation_window(as_of=as_of, horizon_days=horizon_days)
    in_window = [
        session
        for session in sessions
        if window_start <= session.scheduled_date <= window_end
    ]
    race_in_window = any(session.session_type == SessionType.RACE for session in in_window)
    changes: list[SessionChange] = []
    for session in in_window:
        if session.session_type not in REDUCIBLE_SESSION_TYPES:
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
