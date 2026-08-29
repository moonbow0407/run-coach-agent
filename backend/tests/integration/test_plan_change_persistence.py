"""PlanChange / TrainingPlan 持久化约束与确认激活。"""

import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.athlete_recompute_service import AthleteStateRecomputeService
from app.coaching.application.errors import StalePlanChangeError
from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.coaching.application.training_analysis_service import TrainingAnalysisService
from app.coaching.domain.plan.models import PlanChange, PlanChangeStatus, PlanStatus
from app.common.clock import FrozenClock
from app.common.errors import ConflictError, DomainError
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import (
    PlanChangeRow,
    PlannedSessionRow,
    TrainingPlanRow,
)
from app.infrastructure.database.repositories.coaching import (
    SqlAlchemyAthleteStateRepository,
    SqlAlchemyPlanChangeRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyWorkoutRepository,
)
from app.infrastructure.database.repositories.plan_activation import (
    SqlAlchemyPlanActivationStore,
)
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.vertical_slice import seed_vertical_slice


def _services(sessions: async_sessionmaker[AsyncSession], clock: FrozenClock):
    workouts = SqlAlchemyWorkoutRepository(sessions)
    plans = SqlAlchemyPlanRepository(sessions)
    snapshots = SqlAlchemyAthleteStateRepository(sessions)
    recompute = AthleteStateRecomputeService(
        analysis=TrainingAnalysisService(workouts, plans),
        workouts=workouts,
        snapshots=snapshots,
        clock=clock,
    )
    adaptation = PlanAdaptationService(
        plans=plans,
        snapshots=snapshots,
        changes=SqlAlchemyPlanChangeRepository(sessions),
        activation=SqlAlchemyPlanActivationStore(sessions),
        clock=clock,
    )
    return recompute, adaptation, plans


@pytest.mark.asyncio
async def test_training_plan_user_version_unique(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    async with sessions() as session:
        session.add(
            TrainingPlanRow(
                id=new_id(),
                user_id=seed.user_id,
                version=1,
                goal_id=seed.goal_id,
                status=PlanStatus.COMPLETED.value,
                starts_on=date(2026, 7, 20),
                ends_on=date(2026, 9, 27),
                created_at=clock.now(),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_one_unresolved_plan_change_per_user(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    recompute, adaptation, _plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed.user_id, as_of=clock.now())
    first, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed.user_id,
        turn_id=new_id(),
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="高疲劳，降低后续节奏课",
    )
    assert first.status is PlanChangeStatus.DRAFT
    with pytest.raises(ConflictError, match="unresolved_plan_change_exists"):
        await adaptation.propose_reduce_upcoming_load(
            user_id=seed.user_id,
            turn_id=new_id(),
            run_id=new_id(),
            as_of=clock.now(),
            based_on_plan_version=1,
            based_on_state_version=2,
            horizon_days=7,
            reason="再提一次",
        )


@pytest.mark.asyncio
async def test_confirm_activates_new_plan_and_is_idempotent(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    recompute, adaptation, plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed.user_id, as_of=clock.now())
    turn_id = new_id()
    change, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed.user_id,
        turn_id=turn_id,
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="降负荷",
    )
    await adaptation.promote_draft_for_turn(user_id=seed.user_id, turn_id=turn_id)
    result = await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)
    assert result.plan_change.status is PlanChangeStatus.CONFIRMED
    assert result.resulting_plan is not None
    assert result.resulting_plan.version == 2
    assert result.resulting_plan.status is PlanStatus.ACTIVE
    old = await plans.get(user_id=seed.user_id, plan_id=seed.plan_id)
    assert old is not None
    assert old.status is PlanStatus.SUPERSEDED
    sessions_v2 = {item.scheduled_date: item for item in result.resulting_sessions}
    assert sessions_v2[date(2026, 8, 29)].session_type.value == "easy"
    assert sessions_v2[date(2026, 8, 31)].session_type.value == "rest"
    assert sessions_v2[date(2026, 8, 31)].prescription == {}
    again = await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)
    assert again.already_confirmed is True
    assert again.plan_change.resulting_plan_id == result.plan_change.resulting_plan_id
    async with short_session(sessions) as db:
        versions = (
            await db.scalars(
                select(TrainingPlanRow.version).where(TrainingPlanRow.user_id == seed.user_id)
            )
        ).all()
    assert sorted(versions) == [1, 2]


@pytest.mark.asyncio
async def test_confirm_stale_when_plan_version_changed(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    recompute, adaptation, _plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed.user_id, as_of=clock.now())
    turn_id = new_id()
    change, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed.user_id,
        turn_id=turn_id,
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="降负荷",
    )
    await adaptation.promote_draft_for_turn(user_id=seed.user_id, turn_id=turn_id)
    async with short_session(sessions, commit=True) as session:
        old = await session.get(TrainingPlanRow, seed.plan_id)
        assert old is not None
        old.status = PlanStatus.SUPERSEDED.value
        session.add(
            TrainingPlanRow(
                id=new_id(),
                user_id=seed.user_id,
                version=2,
                goal_id=seed.goal_id,
                status=PlanStatus.ACTIVE.value,
                starts_on=date(2026, 7, 20),
                ends_on=date(2026, 9, 27),
                created_at=clock.now(),
            )
        )
    with pytest.raises(StalePlanChangeError):
        await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)
    stored = await adaptation.get(user_id=seed.user_id, plan_change_id=change.id)
    assert stored.status is PlanChangeStatus.STALE


@pytest.mark.asyncio
async def test_confirm_stale_when_state_version_changed(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    recompute, adaptation, _plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed.user_id, as_of=clock.now())
    turn_id = new_id()
    change, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed.user_id,
        turn_id=turn_id,
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="降负荷",
    )
    await adaptation.promote_draft_for_turn(user_id=seed.user_id, turn_id=turn_id)
    await recompute.recompute(
        user_id=seed.user_id, as_of=clock.now() + timedelta(minutes=1)
    )
    with pytest.raises(StalePlanChangeError):
        await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)


@pytest.mark.asyncio
async def test_cross_user_plan_change_is_not_found(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed_a = await seed_vertical_slice(session)
        seed_b = await seed_vertical_slice(session)
    recompute, adaptation, _plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed_a.user_id, as_of=clock.now())
    change, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed_a.user_id,
        turn_id=new_id(),
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="降负荷",
    )
    from app.common.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await adaptation.get(user_id=seed_b.user_id, plan_change_id=change.id)


@pytest.mark.asyncio
async def test_activation_does_not_update_old_sessions(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
        original_ids = set(
            (
                await session.scalars(
                    select(PlannedSessionRow.id).where(
                        PlannedSessionRow.plan_id == seed.plan_id
                    )
                )
            ).all()
        )
    recompute, adaptation, _plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed.user_id, as_of=clock.now())
    turn_id = new_id()
    change, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed.user_id,
        turn_id=turn_id,
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="降负荷",
    )
    await adaptation.promote_draft_for_turn(user_id=seed.user_id, turn_id=turn_id)
    result = await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)
    new_ids = {item.id for item in result.resulting_sessions}
    assert new_ids.isdisjoint(original_ids)
    async with short_session(sessions) as session:
        still = set(
            (
                await session.scalars(
                    select(PlannedSessionRow.id).where(
                        PlannedSessionRow.plan_id == seed.plan_id
                    )
                )
            ).all()
        )
    assert still == original_ids


async def _propose_pending(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
):
    """seed + recompute + propose + promote，返回 (services, seed, plan_change)。"""
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    recompute, adaptation, plans = _services(sessions, clock)
    await recompute.recompute(user_id=seed.user_id, as_of=clock.now())
    turn_id = new_id()
    change, _ = await adaptation.propose_reduce_upcoming_load(
        user_id=seed.user_id,
        turn_id=turn_id,
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="降负荷",
    )
    await adaptation.promote_draft_for_turn(user_id=seed.user_id, turn_id=turn_id)
    return adaptation, plans, seed, change


@pytest.mark.asyncio
async def test_cas_reject_does_not_overwrite_confirmed(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """stale read 的 reject 写入不允许覆盖已 CONFIRMED 的提案。"""
    adaptation, _plans, seed, change = await _propose_pending(sessions, clock)
    result = await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)
    assert result.plan_change.status is PlanChangeStatus.CONFIRMED

    stored = await adaptation.get(user_id=seed.user_id, plan_change_id=change.id)
    assert stored.status is PlanChangeStatus.CONFIRMED
    with pytest.raises(ConflictError):
        await adaptation.reject(user_id=seed.user_id, plan_change_id=change.id)
    final = await adaptation.get(user_id=seed.user_id, plan_change_id=change.id)
    assert final.status is PlanChangeStatus.CONFIRMED
    assert final.resulting_plan_id == result.plan_change.resulting_plan_id


@pytest.mark.asyncio
async def test_cas_reject_after_stale_pending_read(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """在 reject 读到 PENDING 之后、写入之前 confirm 已提交——CAS 必须拒绝写入。"""
    adaptation, _plans, seed, change = await _propose_pending(sessions, clock)
    repo = SqlAlchemyPlanChangeRepository(sessions)
    # 模拟竞态窗口：reject 侧先读到 PENDING，随后 confirm 完成激活。
    stale_read = await repo.get(user_id=seed.user_id, plan_change_id=change.id)
    assert stale_read is not None
    assert stale_read.status is PlanChangeStatus.PENDING_CONFIRMATION
    await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)
    with pytest.raises(ConflictError, match="plan_change_status_conflict"):
        await repo.transition(
            user_id=seed.user_id,
            plan_change_id=change.id,
            expected=PlanChangeStatus.PENDING_CONFIRMATION,
            target=PlanChangeStatus.REJECTED,
            resolved_at=clock.now(),
        )
    final = await adaptation.get(user_id=seed.user_id, plan_change_id=change.id)
    assert final.status is PlanChangeStatus.CONFIRMED


@pytest.mark.asyncio
async def test_concurrent_confirm_and_reject_reach_consistent_state(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """confirm 与 reject 并发：只有一个生效，终态不允许出现交叉组合。"""
    adaptation, plans, seed, change = await _propose_pending(sessions, clock)
    results = await asyncio.gather(
        adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id),
        adaptation.reject(user_id=seed.user_id, plan_change_id=change.id),
        return_exceptions=True,
    )
    confirm_result, reject_result = results
    active = await plans.get_active(user_id=seed.user_id)
    stored = await adaptation.get(user_id=seed.user_id, plan_change_id=change.id)
    if isinstance(confirm_result, BaseException):
        # reject 生效：V1 仍 ACTIVE，提案 REJECTED。
        assert isinstance(reject_result, PlanChange)
        assert isinstance(confirm_result, Exception)
        assert stored.status is PlanChangeStatus.REJECTED
        assert active is not None and active.id == seed.plan_id
        assert active.version == 1
    else:
        # confirm 生效：V2 ACTIVE，提案 CONFIRMED。
        assert isinstance(reject_result, BaseException)
        assert stored.status is PlanChangeStatus.CONFIRMED
        assert active is not None and active.version == 2
        assert stored.resulting_plan_id == active.id


def _tamper_horizon(payload: dict) -> dict:
    return {"horizon_days": 365, "changes": payload["changes"]}


def _tamper_empty(payload: dict) -> dict:
    return {"horizon_days": payload["horizon_days"], "changes": []}


def _tamper_duplicate(payload: dict) -> dict:
    return {**payload, "changes": payload["changes"] * 2}


def _tamper_old_title(payload: dict) -> dict:
    return {
        **payload,
        "changes": [{**payload["changes"][0], "old_title": "被篡改的标题"}],
    }


def _tamper_new_prescription(payload: dict) -> dict:
    return {
        **payload,
        "changes": [{**payload["changes"][0], "new_prescription": {"pace": "5:00"}}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [_tamper_horizon, _tamper_empty, _tamper_duplicate, _tamper_old_title, _tamper_new_prescription],
    ids=["horizon", "empty", "duplicate", "old_title", "new_prescription"],
)
async def test_confirm_rejects_tampered_payload_without_activating(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    mutate,
) -> None:
    """直接篡改数据库 payload 后 confirm 必须失败：无 Plan V2、V1 仍 ACTIVE。

    证明 Proposal Validation 与 Activation Validation 是两层独立安全边界。
    """
    adaptation, plans, seed, change = await _propose_pending(sessions, clock)
    async with short_session(sessions, commit=True) as session:
        row = await session.get(PlanChangeRow, change.id)
        assert row is not None
        row.payload = mutate(row.payload)

    with pytest.raises(DomainError):
        await adaptation.confirm(user_id=seed.user_id, plan_change_id=change.id)

    stored = await adaptation.get(user_id=seed.user_id, plan_change_id=change.id)
    assert stored.status is PlanChangeStatus.PENDING_CONFIRMATION
    active = await plans.get_active(user_id=seed.user_id)
    assert active is not None
    assert active.id == seed.plan_id
    assert active.version == 1
    async with short_session(sessions) as session:
        versions = (
            await session.scalars(
                select(TrainingPlanRow.version).where(TrainingPlanRow.user_id == seed.user_id)
            )
        ).all()
    assert sorted(versions) == [1]
