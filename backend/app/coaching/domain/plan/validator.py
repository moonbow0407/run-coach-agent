"""PlanChange 激活前的领域校验。禁止信任库里的 JSON 曾经合法。"""

from collections.abc import Sequence
from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.plan.adaptation import (
    MAX_HORIZON_DAYS,
    MIN_HORIZON_DAYS,
    REDUCIBLE_SESSION_TYPES,
    adaptation_window,
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


def validate_reduce_upcoming_load_activation(
    *,
    user_id: UUID,
    plan_change: PlanChange,
    active_plan: TrainingPlan,
    latest_state: AthleteStateSnapshot,
    base_sessions: Sequence[PlannedSession],
) -> None:
    """确认激活前重新验证 payload 与新鲜度以外的全部结构约束。

    payload 是持久化在数据库里的 JSON，可能被篡改、损坏或由旁路路径写入；
    这里的每一条检查都不假设"它之前验证过"。
    """
    # 归属与类型：提案必须属于该用户，且是系统支持的调整类型。
    if plan_change.user_id != user_id:
        raise DomainError("plan_change_user_mismatch")
    if plan_change.change_type is not PlanChangeType.REDUCE_UPCOMING_LOAD:
        raise DomainError("unsupported_change_type")
    # 新鲜度：基准计划仍是 ACTIVE，且 id / 版本与提案时完全一致。
    if active_plan.status is not PlanStatus.ACTIVE:
        raise DomainError("base_plan_not_active")
    if active_plan.id != plan_change.from_plan_id:
        raise DomainError("base_plan_id_mismatch")
    if active_plan.version != plan_change.from_plan_version:
        raise DomainError("base_plan_version_mismatch")
    # 状态依据：快照 id / 版本必须仍是提案时的那一版。
    if latest_state.id != plan_change.based_on_state_id:
        raise DomainError("athlete_state_id_mismatch")
    if latest_state.version != plan_change.based_on_state_version:
        raise DomainError("athlete_state_version_mismatch")

    # 重新声明 v1 安全前提，不依赖"提案时检查过"这一事实。
    ensure_v1_reduction_precondition(latest_state.fatigue_level, latest_state.recovery_level)

    # payload 结构：窗口长度合法，且至少改动一个课次。
    if not MIN_HORIZON_DAYS <= plan_change.payload.horizon_days <= MAX_HORIZON_DAYS:
        raise DomainError("horizon_days_out_of_range")
    changes = plan_change.payload.changes
    if not changes:
        # 空 diff 会激活出一个与当前版本完全相同的"空版本"计划。
        raise DomainError("empty_plan_change")

    # 逐条 diff 校验：以基准计划的课次为唯一事实来源核对替换内容。
    sessions_by_id = {session.id: session for session in base_sessions}
    window_start, window_end = adaptation_window(
        as_of=plan_change.as_of,
        horizon_days=plan_change.payload.horizon_days,
    )
    seen_session_ids: set[UUID] = set()
    for change in changes:
        # 同一课次被替换两次会导致激活结果不确定。
        if change.source_session_id in seen_session_ids:
            raise DomainError("duplicate_source_session")
        seen_session_ids.add(change.source_session_id)
        # 替换目标必须真实存在于基准计划中。
        source = sessions_by_id.get(change.source_session_id)
        if source is None:
            raise DomainError("source_session_not_in_base_plan")
        # 日期三重校验：在调整窗口内、在计划周期内、且与源课次一致。
        if not (window_start <= change.scheduled_date <= window_end):
            raise DomainError("session_date_outside_window")
        if not (active_plan.starts_on <= change.scheduled_date <= active_plan.ends_on):
            raise DomainError("session_date_outside_plan_range")
        if change.scheduled_date != source.scheduled_date:
            raise DomainError("session_date_mismatch")
        # 比赛课任何情况下都不得被改动。
        if source.session_type is SessionType.RACE or change.from_type is SessionType.RACE:
            raise DomainError("race_session_must_not_change")
        # 只允许 TEMPO / INTERVAL → REST 这一种替换形态。
        if source.session_type not in REDUCIBLE_SESSION_TYPES:
            raise DomainError("session_type_not_reducible")
        if change.from_type is not source.session_type:
            raise DomainError("from_type_mismatch")
        if change.to_type is not SessionType.REST:
            raise DomainError("to_type_must_be_rest")
        # 旧标题 / 旧处方必须与基准计划逐字一致，防止提案基于过期数据。
        if change.old_title != source.title:
            raise DomainError("old_title_mismatch")
        if change.old_prescription != source.prescription:
            raise DomainError("old_prescription_mismatch")
        # 新内容必须与领域生成的确定性结果完全一致，不允许模型自由发挥。
        if change.new_title != rest_replacement_title(source.title):
            raise DomainError("new_title_mismatch")
        if change.new_prescription != {}:
            raise DomainError("new_prescription_must_be_empty")

    # 兜底复查：即使 diff 未引用，基准计划中的比赛课也不得出现在改动集。
    changed_ids = {change.source_session_id for change in changes}
    for session in base_sessions:
        if session.session_type is SessionType.RACE and session.id in changed_ids:
            raise DomainError("race_session_must_not_change")
