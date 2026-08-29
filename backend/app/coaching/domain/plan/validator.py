"""PlanChange 激活前的领域校验。禁止信任库里的 JSON 曾经合法。"""

from collections.abc import Sequence
from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.plan.adaptation import (
    REDUCIBLE_SESSION_TYPES,
    adaptation_window,
)
from app.coaching.domain.plan.models import (
    PlanChange,
    PlanChangeType,
    PlannedSession,
    PlanStatus,
    SessionType,
    TrainingPlan,
)
from app.common.errors import DomainError


def validate_reduce_upcoming_load_activation(
    *,
    user_id: UUID,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    latest_state: AthleteStateSnapshot,
    base_sessions: Sequence[PlannedSession],
) -> None:
    """确认激活前再次验证 payload 与新鲜度以外的结构约束。"""
    if plan_change.user_id != user_id:
        raise DomainError("plan_change_user_mismatch")
    if plan_change.change_type is not PlanChangeType.REDUCE_UPCOMING_LOAD:
        raise DomainError("unsupported_change_type")
    if active_plan.status is not PlanStatus.ACTIVE:
        raise DomainError("base_plan_not_active")
    if active_plan.id != plan_change.from_plan_id:
        raise DomainError("base_plan_id_mismatch")
    if active_plan.version != plan_change.from_plan_version:
        raise DomainError("base_plan_version_mismatch")
    if latest_state.id != plan_change.based_on_state_id:
        raise DomainError("athlete_state_id_mismatch")
    if latest_state.version != plan_change.based_on_state_version:
        raise DomainError("athlete_state_version_mismatch")

    sessions_by_id = {session.id: session for session in base_sessions}
    window_start, window_end = adaptation_window(
        as_of=plan_change.as_of,
        horizon_days=plan_change.payload.horizon_days,
    )
    for change in plan_change.payload.changes:
        source = sessions_by_id.get(change.source_session_id)
        if source is None:
            raise DomainError("source_session_not_in_base_plan")
        if not (window_start <= change.scheduled_date <= window_end):
            raise DomainError("session_date_outside_window")
        if change.scheduled_date != source.scheduled_date:
            raise DomainError("session_date_mismatch")
        if source.session_type is SessionType.RACE or change.from_type is SessionType.RACE:
            raise DomainError("race_session_must_not_change")
        if source.session_type not in REDUCIBLE_SESSION_TYPES:
            raise DomainError("session_type_not_reducible")
        if change.from_type is not source.session_type:
            raise DomainError("from_type_mismatch")
        if change.to_type is not SessionType.REST:
            raise DomainError("to_type_must_be_rest")
        if change.new_prescription != {}:
            raise DomainError("new_prescription_must_be_empty")

    changed_ids = {change.source_session_id for change in plan_change.payload.changes}
    for session in base_sessions:
        if session.session_type is SessionType.RACE and session.id in changed_ids:
            raise DomainError("race_session_must_not_change")
