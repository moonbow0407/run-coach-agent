"""PlanChange 激活前的领域校验。禁止信任库里的 JSON 曾经合法。"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.plan.adaptation import (
    HARD_SESSION_TYPES,
    MAX_HORIZON_DAYS,
    MIN_HORIZON_DAYS,
    adaptation_window,
    easy_replacement_prescription,
    easy_replacement_title,
    ensure_v1_reduction_precondition,
    rest_replacement_title,
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


def validate_plan_change_activation(
    *,
    user_id: UUID,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    latest_state: AthleteStateSnapshot,
    base_sessions: Sequence[PlannedSession],
) -> None:
    """按 change_type 分发到对应激活校验；不支持的类型立即失败。"""
    if plan_change.change_type is PlanChangeType.REDUCE_UPCOMING_LOAD:
        validate_reduce_upcoming_load_activation(
            user_id=user_id,
            plan_change=plan_change,
            active_plan=active_plan,
            latest_state=latest_state,
            base_sessions=base_sessions,
        )
        return
    if plan_change.change_type is PlanChangeType.CONVERT_HARD_SESSIONS_TO_EASY:
        validate_convert_hard_sessions_to_easy_activation(
            user_id=user_id,
            plan_change=plan_change,
            active_plan=active_plan,
            latest_state=latest_state,
            base_sessions=base_sessions,
        )
        return
    raise DomainError("unsupported_change_type")


def validate_reduce_upcoming_load_activation(
    *,
    user_id: UUID,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    latest_state: AthleteStateSnapshot,
    base_sessions: Sequence[PlannedSession],
) -> None:
    """确认激活前重新验证 reduce_upcoming_load 的全部结构约束。"""
    _validate_common_freshness(
        user_id=user_id,
        plan_change=plan_change,
        active_plan=active_plan,
        latest_state=latest_state,
        expected_type=PlanChangeType.REDUCE_UPCOMING_LOAD,
    )
    ensure_v1_reduction_precondition(latest_state.fatigue_level, latest_state.recovery_level)
    _validate_session_replacements(
        plan_change=plan_change,
        active_plan=active_plan,
        base_sessions=base_sessions,
        allowed_from_types=HARD_SESSION_TYPES,
        required_to_type=SessionType.REST,
        expected_new_title=rest_replacement_title,
        expected_new_prescription=lambda _old: {},
    )


def validate_convert_hard_sessions_to_easy_activation(
    *,
    user_id: UUID,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    latest_state: AthleteStateSnapshot,
    base_sessions: Sequence[PlannedSession],
) -> None:
    """确认激活前重新验证 convert_hard_sessions_to_easy 的全部结构约束。"""
    _validate_common_freshness(
        user_id=user_id,
        plan_change=plan_change,
        active_plan=active_plan,
        latest_state=latest_state,
        expected_type=PlanChangeType.CONVERT_HARD_SESSIONS_TO_EASY,
    )
    ensure_v1_reduction_precondition(latest_state.fatigue_level, latest_state.recovery_level)
    _validate_session_replacements(
        plan_change=plan_change,
        active_plan=active_plan,
        base_sessions=base_sessions,
        allowed_from_types=HARD_SESSION_TYPES,
        required_to_type=SessionType.EASY,
        expected_new_title=easy_replacement_title,
        expected_new_prescription=easy_replacement_prescription,
    )


def _validate_common_freshness(
    *,
    user_id: UUID,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    latest_state: AthleteStateSnapshot,
    expected_type: PlanChangeType,
) -> None:
    if plan_change.user_id != user_id:
        raise DomainError("plan_change_user_mismatch")
    if plan_change.change_type is not expected_type:
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


def _validate_session_replacements(
    *,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    base_sessions: Sequence[PlannedSession],
    allowed_from_types: frozenset[SessionType],
    required_to_type: SessionType,
    # 期望的新标题 / 新处方生成器：与领域生成器共用同一确定性规则。
    expected_new_title: Callable[[str], str],
    expected_new_prescription: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    if not MIN_HORIZON_DAYS <= plan_change.payload.horizon_days <= MAX_HORIZON_DAYS:
        raise DomainError("horizon_days_out_of_range")
    changes = plan_change.payload.changes
    if not changes:
        raise DomainError("empty_plan_change")

    sessions_by_id = {session.id: session for session in base_sessions}
    window_start, window_end = adaptation_window(
        as_of=plan_change.as_of,
        horizon_days=plan_change.payload.horizon_days,
    )
    seen_session_ids: set[UUID] = set()
    for change in changes:
        if change.source_session_id in seen_session_ids:
            raise DomainError("duplicate_source_session")
        seen_session_ids.add(change.source_session_id)
        source = sessions_by_id.get(change.source_session_id)
        if source is None:
            raise DomainError("source_session_not_in_base_plan")
        if not (window_start <= change.scheduled_date <= window_end):
            raise DomainError("session_date_outside_window")
        if not (active_plan.starts_on <= change.scheduled_date <= active_plan.ends_on):
            raise DomainError("session_date_outside_plan_range")
        if change.scheduled_date != source.scheduled_date:
            raise DomainError("session_date_mismatch")
        if source.session_type is SessionType.RACE or change.from_type is SessionType.RACE:
            raise DomainError("race_session_must_not_change")
        if source.session_type not in allowed_from_types:
            raise DomainError("session_type_not_reducible")
        if change.from_type is not source.session_type:
            raise DomainError("from_type_mismatch")
        if change.to_type is not required_to_type:
            raise DomainError(
                "to_type_must_be_rest"
                if required_to_type is SessionType.REST
                else "to_type_must_be_easy"
            )
        if change.old_title != source.title:
            raise DomainError("old_title_mismatch")
        if change.old_prescription != source.prescription:
            raise DomainError("old_prescription_mismatch")
        if change.new_title != expected_new_title(source.title):
            raise DomainError("new_title_mismatch")
        if change.new_prescription != expected_new_prescription(source.prescription):
            raise DomainError("new_prescription_mismatch")

    changed_ids = {change.source_session_id for change in changes}
    for session in base_sessions:
        if session.session_type is SessionType.RACE and session.id in changed_ids:
            raise DomainError("race_session_must_not_change")
