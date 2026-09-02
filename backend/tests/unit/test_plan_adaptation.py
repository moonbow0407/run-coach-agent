"""reduce_upcoming_load 与 PlanChangeValidator 的纯领域测试。"""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.coaching.domain.athlete.models import AthleteStateSnapshot, FatigueLevel, RecoveryLevel
from app.coaching.domain.plan.adaptation import generate_reduce_upcoming_load
from app.coaching.domain.plan.models import (
    PlanChange,
    PlanChangePayload,
    PlanChangeStatus,
    PlanChangeType,
    PlannedSession,
    PlanStatus,
    SessionChange,
    SessionType,
    TrainingPlan,
)
from app.coaching.domain.plan.validator import validate_reduce_upcoming_load_activation
from app.common.errors import DomainError
from app.common.ids import new_id

AS_OF = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


def _session(
    *,
    scheduled_date: date,  # 课次计划日期
    session_type: SessionType,  # 课型（EASY/TEMPO/INTERVAL/RACE 等）
    title: str = "课次",  # 课次标题（校验 old_title 匹配时依赖）
    prescription: dict | None = None,  # 训练处方（配速等）
    plan_id=None,
) -> PlannedSession:
    return PlannedSession(
        id=new_id(),
        plan_id=plan_id or new_id(),
        scheduled_date=scheduled_date,
        session_type=session_type,
        title=title,
        prescription=prescription or {"pace": "5:10"},
    )


def test_tempo_and_interval_become_rest_in_window() -> None:
    """验证：窗口内的节奏/间歇课改为休息且标题/处方被改写，轻松跑保持不动。"""
    tempo = _session(
        scheduled_date=date(2026, 8, 31),
        session_type=SessionType.TEMPO,
        title="第 6 周节奏跑",
    )
    interval = _session(
        scheduled_date=date(2026, 9, 2),
        session_type=SessionType.INTERVAL,
        title="间歇",
    )
    easy = _session(scheduled_date=date(2026, 8, 29), session_type=SessionType.EASY)
    result = generate_reduce_upcoming_load(
        as_of=AS_OF,
        horizon_days=7,
        sessions=[tempo, interval, easy],
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.FAIR,
    )
    changed = {item.source_session_id: item for item in result.payload.changes}
    assert tempo.id in changed
    assert interval.id in changed
    assert easy.id not in changed
    assert changed[tempo.id].to_type is SessionType.REST
    assert changed[tempo.id].new_title == "恢复休息（调整自：第 6 周节奏跑）"
    assert changed[tempo.id].new_prescription == {}
    assert result.window_start == date(2026, 8, 29)
    assert result.window_end == date(2026, 9, 4)


def test_race_is_not_modified() -> None:
    """验证：比赛课永不调整，并打上 race_session_not_modified 标记。"""
    race = _session(scheduled_date=date(2026, 8, 30), session_type=SessionType.RACE)
    tempo = _session(scheduled_date=date(2026, 8, 31), session_type=SessionType.TEMPO)
    result = generate_reduce_upcoming_load(
        as_of=AS_OF,
        horizon_days=7,
        sessions=[race, tempo],
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=None,
    )
    assert result.race_session_not_modified is True
    assert all(item.source_session_id != race.id for item in result.payload.changes)


def test_empty_adaptation_rejected() -> None:
    """验证：窗口内无可调整课次时拒绝生成空变更（不伪造降负荷）。"""
    easy = _session(scheduled_date=date(2026, 8, 29), session_type=SessionType.EASY)
    with pytest.raises(DomainError, match="no_applicable_sessions"):
        generate_reduce_upcoming_load(
            as_of=AS_OF,
            horizon_days=7,
            sessions=[easy],
            fatigue_level=FatigueLevel.HIGH,
            recovery_level=None,
        )


def test_precondition_requires_high_or_poor() -> None:
    """验证：疲劳/恢复未达阈值时拒绝降负荷（防止过度干预）。"""
    tempo = _session(scheduled_date=date(2026, 8, 31), session_type=SessionType.TEMPO)
    with pytest.raises(DomainError, match="state_does_not_require_v1_reduction"):
        generate_reduce_upcoming_load(
            as_of=AS_OF,
            horizon_days=7,
            sessions=[tempo],
            fatigue_level=FatigueLevel.MODERATE,
            recovery_level=RecoveryLevel.FAIR,
        )


def test_does_not_change_long_run_other_or_rest() -> None:
    """验证：长距离/其他/休息课不在可调整范围；全部不可调时报 no_applicable_sessions。"""
    sessions = [
        _session(scheduled_date=date(2026, 8, 29), session_type=SessionType.LONG_RUN),
        _session(scheduled_date=date(2026, 8, 30), session_type=SessionType.OTHER),
        _session(scheduled_date=date(2026, 8, 31), session_type=SessionType.REST),
    ]
    with pytest.raises(DomainError, match="no_applicable_sessions"):
        generate_reduce_upcoming_load(
            as_of=AS_OF,
            horizon_days=7,
            sessions=sessions,
            fatigue_level=None,
            recovery_level=RecoveryLevel.POOR,
        )


def test_validator_rejects_race_replacement() -> None:
    """验证：激活校验兜底拦截「把比赛课改成休息」的异常 payload（生成器本不该产出）。"""
    plan_id = new_id()
    user_id = uuid4()
    race = _session(
        scheduled_date=date(2026, 8, 30),
        session_type=SessionType.RACE,
        plan_id=plan_id,
    )
    plan = TrainingPlan(
        id=plan_id,
        user_id=user_id,
        version=1,
        goal_id=None,
        status=PlanStatus.ACTIVE,
        starts_on=date(2026, 7, 20),
        ends_on=date(2026, 9, 27),
        created_at=AS_OF,
    )
    state = AthleteStateSnapshot(
        id=new_id(),
        user_id=user_id,
        version=2,
        as_of=AS_OF,
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.FAIR,
        recent_training_load=None,
        workout_completion_rate=None,
        training_load_coverage=0.3,
        signals=(),
        confidence=0.8,
        algorithm_version="phase3.v1",
        created_at=AS_OF,
    )
    change = PlanChange(
        id=new_id(),
        user_id=user_id,
        from_plan_id=plan.id,
        from_plan_version=1,
        based_on_state_id=state.id,
        based_on_state_version=2,
        source_turn_id=new_id(),
        source_run_id=new_id(),
        as_of=AS_OF,
        change_type=PlanChangeType.REDUCE_UPCOMING_LOAD,
        payload=PlanChangePayload(
            horizon_days=7,
            changes=(
                SessionChange(
                    source_session_id=race.id,
                    scheduled_date=race.scheduled_date,
                    from_type=SessionType.RACE,
                    to_type=SessionType.REST,
                    old_title=race.title,
                    new_title="x",
                    old_prescription={},
                    new_prescription={},
                ),
            ),
        ),
        reason="bad",
        status=PlanChangeStatus.PENDING_CONFIRMATION,
        created_at=AS_OF,
        resolved_at=None,
        resulting_plan_id=None,
    )
    with pytest.raises(DomainError, match="race_session_must_not_change"):
        validate_reduce_upcoming_load_activation(
            user_id=user_id,
            plan_change=change,
            active_plan=plan,
            latest_state=state,
            base_sessions=[race],
        )


def _activation_fixture():
    """用领域生成器产出一份完全合法的激活输入，供各负例逐一篡改。"""
    plan_id = new_id()
    user_id = uuid4()
    easy = _session(
        scheduled_date=date(2026, 8, 29),
        session_type=SessionType.EASY,
        title="轻松跑",
        plan_id=plan_id,
    )
    tempo = _session(
        scheduled_date=date(2026, 8, 31),
        session_type=SessionType.TEMPO,
        title="节奏跑",
        plan_id=plan_id,
    )
    plan = TrainingPlan(
        id=plan_id,
        user_id=user_id,
        version=1,
        goal_id=None,
        status=PlanStatus.ACTIVE,
        starts_on=date(2026, 7, 20),
        ends_on=date(2026, 9, 27),
        created_at=AS_OF,
    )
    state = AthleteStateSnapshot(
        id=new_id(),
        user_id=user_id,
        version=2,
        as_of=AS_OF,
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.FAIR,
        recent_training_load=None,
        workout_completion_rate=None,
        training_load_coverage=0.3,
        signals=(),
        confidence=0.8,
        algorithm_version="phase3.v1",
        created_at=AS_OF,
    )
    result = generate_reduce_upcoming_load(
        as_of=AS_OF,
        horizon_days=7,
        sessions=[easy, tempo],
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.FAIR,
    )
    change = PlanChange(
        id=new_id(),
        user_id=user_id,
        from_plan_id=plan.id,
        from_plan_version=1,
        based_on_state_id=state.id,
        based_on_state_version=2,
        source_turn_id=new_id(),
        source_run_id=new_id(),
        as_of=AS_OF,
        change_type=PlanChangeType.REDUCE_UPCOMING_LOAD,
        payload=result.payload,
        reason="降负荷",
        status=PlanChangeStatus.PENDING_CONFIRMATION,
        created_at=AS_OF,
        resolved_at=None,
        resulting_plan_id=None,
    )
    return change, plan, state, [easy, tempo]


def _validate(change, plan, state, sessions) -> None:
    """以 plan 归属用户执行激活校验；合法时静默通过。"""
    validate_reduce_upcoming_load_activation(
        user_id=plan.user_id,
        plan_change=change,
        active_plan=plan,
        latest_state=state,
        base_sessions=sessions,
    )


def test_validator_accepts_generated_payload() -> None:
    """验证：生成器产出的合法 payload 必须能通过激活校验（生成与校验口径一致）。"""
    change, plan, state, sessions = _activation_fixture()
    _validate(change, plan, state, sessions)


def test_validator_rejects_out_of_range_horizon() -> None:
    """验证：被篡改到范围外的 horizon 被拒绝。"""
    change, plan, state, sessions = _activation_fixture()
    # dataclasses.replace：复制 frozen dataclass 并替换指定字段
    tampered = replace(change, payload=replace(change.payload, horizon_days=365))
    with pytest.raises(DomainError, match="horizon_days_out_of_range"):
        _validate(tampered, plan, state, sessions)


def test_validator_rejects_empty_changes() -> None:
    """验证：空变更集的 payload 在激活时被拒绝。"""
    change, plan, state, sessions = _activation_fixture()
    tampered = replace(change, payload=replace(change.payload, changes=()))
    with pytest.raises(DomainError, match="empty_plan_change"):
        _validate(tampered, plan, state, sessions)


def test_validator_rejects_duplicate_source_session() -> None:
    """验证：同一课次在变更集中重复出现被拒绝（防止双重改写）。"""
    change, plan, state, sessions = _activation_fixture()
    duplicated = replace(
        change, payload=replace(change.payload, changes=change.payload.changes * 2)
    )
    with pytest.raises(DomainError, match="duplicate_source_session"):
        _validate(duplicated, plan, state, sessions)


def test_validator_rejects_tampered_old_fields() -> None:
    """验证：old/new 各字段与基线不符时逐项被拒（payload 不可被篡改）。"""
    change, plan, state, sessions = _activation_fixture()
    first = change.payload.changes[0]
    tampered_change = replace(first, old_title="被篡改的标题")
    tampered = replace(
        change,
        payload=replace(
            change.payload, changes=(tampered_change, *change.payload.changes[1:])
        ),
    )
    with pytest.raises(DomainError, match="old_title_mismatch"):
        _validate(tampered, plan, state, sessions)

    tampered_prescription = replace(
        first, old_prescription={"pace": "被篡改的处方"}
    )
    tampered = replace(
        change,
        payload=replace(
            change.payload, changes=(tampered_prescription, *change.payload.changes[1:])
        ),
    )
    with pytest.raises(DomainError, match="old_prescription_mismatch"):
        _validate(tampered, plan, state, sessions)

    tampered_new_title = replace(first, new_title="任意标题")
    tampered = replace(
        change,
        payload=replace(
            change.payload, changes=(tampered_new_title, *change.payload.changes[1:])
        ),
    )
    with pytest.raises(DomainError, match="new_title_mismatch"):
        _validate(tampered, plan, state, sessions)


def test_validator_rejects_session_date_outside_plan_range() -> None:
    """验证：课次日期超出 Plan 起止范围时激活被拒绝。"""
    change, plan, state, sessions = _activation_fixture()
    # 窗口内、但落在 Plan 日期范围之外（ends_on 早于课次日期）。
    shortened_plan = replace(plan, ends_on=date(2026, 8, 30))
    with pytest.raises(DomainError, match="session_date_outside_plan_range"):
        _validate(change, shortened_plan, state, sessions)


def test_validator_recheck_safety_precondition() -> None:
    """验证：激活时复核安全前提——即使 state id/version 匹配，前提不满足仍拒绝。"""
    change, plan, state, sessions = _activation_fixture()
    # 即使 state id/version 匹配，也要求 state 本身仍满足 v1 前提。
    moderate_state = replace(
        state, fatigue_level=FatigueLevel.MODERATE, recovery_level=RecoveryLevel.GOOD
    )
    with pytest.raises(DomainError, match="state_does_not_require_v1_reduction"):
        _validate(change, plan, moderate_state, sessions)
