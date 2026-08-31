"""AthleteStateSnapshot 追加语义：append-only、版本单调、用户锁、查询不计算。"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.athlete_recompute_service import AthleteStateRecomputeService
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.contracts.durable_events import ATHLETE_STATE_RECOMPUTED_V1
from app.coaching.domain.athlete.models import FatigueLevel, RecoveryLevel
from app.common.clock import FrozenClock
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import AthleteStateSnapshotRow
from app.infrastructure.database.models.outbox import OutboxEventRow
from app.infrastructure.database.repositories.athlete_recompute import (
    SqlAlchemyAthleteStateRecomputeUnitOfWork,
)
from app.infrastructure.database.repositories.coaching import (
    SqlAlchemyAthleteStateRepository,
)
from app.infrastructure.database.session import short_session
from app.infrastructure.outbox.writer import OutboxWriter
from app.infrastructure.seed.vertical_slice import seed_vertical_slice


def _recompute_service(
    sessions: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> AthleteStateRecomputeService:
    return AthleteStateRecomputeService(
        unit_of_work=SqlAlchemyAthleteStateRecomputeUnitOfWork(
            sessions, OutboxWriter()
        ),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_vertical_slice_recompute_appends_v2_high_fair(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    service = _recompute_service(sessions, clock)
    snapshot = await service.recompute(user_id=seed.user_id, as_of=clock.now())
    assert snapshot.version == 2
    assert snapshot.algorithm_version == "phase3.v1"
    assert snapshot.fatigue_level is FatigueLevel.HIGH
    assert snapshot.recovery_level is RecoveryLevel.FAIR
    assert snapshot.training_load_coverage is not None
    assert snapshot.training_load_coverage < 0.5
    assert snapshot.recent_training_load is None
    assert snapshot.workout_completion_rate is None
    assert snapshot.as_of == clock.now()
    async with short_session(sessions) as session:
        event = await session.scalar(
            select(OutboxEventRow).where(
                OutboxEventRow.event_type == ATHLETE_STATE_RECOMPUTED_V1,
                OutboxEventRow.aggregate_id == snapshot.id,
            )
        )
    assert event is not None
    assert event.user_id == seed.user_id
    assert event.payload["snapshot_version"] == 2


@pytest.mark.asyncio
async def test_recompute_ignores_feedback_created_after_as_of(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """情况 A 端到端：as_of 之后补报的高疲劳反馈不得进入历史快照。"""
    from datetime import UTC, datetime

    from app.infrastructure.database.models.coaching import (
        WorkoutFeedbackRow,
        WorkoutRow,
    )
    from app.infrastructure.database.models.user import UserRow

    user_id = new_id()
    workout_id = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=user_id, created_at=clock.now(), updated_at=clock.now()))
        await session.flush()
        session.add(
            WorkoutRow(
                id=workout_id,
                user_id=user_id,
                started_at=datetime(2026, 8, 27, 6, 0, tzinfo=UTC),
                distance_m=8000,
                duration_s=2520,
                avg_heart_rate=168,
                max_heart_rate=181,
                workout_type="interval",
                source="manual",
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        await session.flush()
        session.add(
            WorkoutFeedbackRow(
                id=new_id(),
                user_id=user_id,
                workout_id=workout_id,
                perceived_exertion=10,
                subjective_fatigue=10,
                soreness=10,
                note="as_of 之后才补报",
                created_at=clock.now() + timedelta(days=2),
                updated_at=clock.now() + timedelta(days=2),
            )
        )
    service = _recompute_service(sessions, clock)
    snapshot = await service.recompute(user_id=user_id, as_of=clock.now())
    # 若未来反馈泄漏进评估，fatigue=10 会把结果推成 HIGH；正确行为是 UNKNOWN。
    assert snapshot.fatigue_level is None
    codes = {signal.code for signal in snapshot.signals}
    assert "insufficient_recent_feedback" in codes


@pytest.mark.asyncio
async def test_same_as_of_identical_assessment_does_not_insert(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    service = _recompute_service(sessions, clock)
    first = await service.recompute(user_id=seed.user_id, as_of=clock.now())
    second = await service.recompute(user_id=seed.user_id, as_of=clock.now())
    assert first.id == second.id
    assert first.version == second.version == 2
    async with short_session(sessions) as session:
        count = await session.scalar(
            select(func.count())
            .select_from(AthleteStateSnapshotRow)
            .where(AthleteStateSnapshotRow.user_id == seed.user_id)
        )
        event_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEventRow)
            .where(
                OutboxEventRow.user_id == seed.user_id,
                OutboxEventRow.event_type == ATHLETE_STATE_RECOMPUTED_V1,
            )
        )
    assert count == 2  # fixture V1 + 一次正式 V2
    assert event_count == 1


@pytest.mark.asyncio
async def test_older_trigger_is_obsolete_noop(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    service = _recompute_service(sessions, clock)
    current = await service.recompute(user_id=seed.user_id, as_of=clock.now())
    obsolete = await service.recompute(
        user_id=seed.user_id, as_of=clock.now() - timedelta(days=2)
    )
    assert obsolete.id == current.id
    assert obsolete.version == current.version


@pytest.mark.asyncio
async def test_newer_as_of_appends_monotonic_version(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    service = _recompute_service(sessions, clock)
    v2 = await service.recompute(user_id=seed.user_id, as_of=clock.now())
    v3 = await service.recompute(
        user_id=seed.user_id, as_of=clock.now() + timedelta(minutes=1)
    )
    assert v2.version == 2
    assert v3.version == 3
    assert v3.as_of > v2.as_of


@pytest.mark.asyncio
async def test_concurrent_recompute_does_not_lose_versions(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    service = _recompute_service(sessions, clock)
    first, second = await asyncio.gather(
        service.recompute(user_id=seed.user_id, as_of=clock.now()),
        service.recompute(user_id=seed.user_id, as_of=clock.now()),
    )
    assert {first.version, second.version} == {2}
    assert first.id == second.id


@pytest.mark.asyncio
async def test_query_path_does_not_compute_or_insert(
    sessions: async_sessionmaker[AsyncSession],
    user_id,
) -> None:
    repo = SqlAlchemyAthleteStateRepository(sessions)
    query = AthleteStateQueryService(repo)
    assert await query.get_latest_athlete_state(user_id=user_id) is None
    async with short_session(sessions) as session:
        count = await session.scalar(
            select(func.count())
            .select_from(AthleteStateSnapshotRow)
            .where(AthleteStateSnapshotRow.user_id == user_id)
        )
    assert count == 0


@pytest.mark.asyncio
async def test_snapshot_cross_user_isolation(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed_a = await seed_vertical_slice(session)
        seed_b = await seed_vertical_slice(session)
    service = _recompute_service(sessions, clock)
    await service.recompute(user_id=seed_a.user_id, as_of=clock.now())
    query = AthleteStateQueryService(SqlAlchemyAthleteStateRepository(sessions))
    latest_b = await query.get_latest_athlete_state(user_id=seed_b.user_id)
    assert latest_b is not None
    assert latest_b.version == 1
    assert latest_b.algorithm_version == "seed-fixture"
