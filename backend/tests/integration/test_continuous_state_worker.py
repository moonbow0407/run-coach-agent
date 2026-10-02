"""Workout durable event 通过正式 handler 持续产生可信时间的 Athlete State。"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.coaching.domain.workout.models import WorkoutSource, WorkoutType
from app.coaching.ports.workout_mutation_store import WorkoutMutation
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import AthleteStateSnapshotRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from tests.durable import drain_durable_tasks


@pytest.mark.asyncio
async def test_late_historical_workout_uses_availability_cutoff_not_fact_time(
    make_app,
    user_id,
    clock,
) -> None:
    """验证：迟到 30 天的历史课次触发重算时，快照 as_of 取事件可用时间而非事实发生时间；事件重放被 receipt 幂等拦截。"""
    app = make_app()
    # 构造一次发生在 30 天前的课次（事实时间远早于入库时间）。
    workout = await app.state.workout_command_service.record(
        user_id=user_id,
        mutation=WorkoutMutation(
            started_at=clock.now() - timedelta(days=30),
            distance_m=5000,
            duration_s=1800,
            avg_heart_rate=140,
            max_heart_rate=155,
            workout_type=WorkoutType.EASY,
            source=WorkoutSource.MANUAL,
        ),
        event_metadata=EventMetadata(correlation_id=new_id(), trace_id=new_id()),
    )
    results = await drain_durable_tasks(app)
    snapshot = await app.state.athlete_service.get_latest_athlete_state(user_id=user_id)

    assert workout.started_at == clock.now() - timedelta(days=30)
    # 事实时间保留原始值，但快照的可信时间锚定在事件可用时刻。
    assert workout.updated_at == clock.now()
    assert snapshot is not None
    assert snapshot.version == 1
    assert snapshot.as_of == workout.updated_at
    assert any(result.status == "success" for result in results)

    # 原 event 迟到重放时，receipt 与 service cutoff 都阻止 as_of/version 回退。
    replay_results = await drain_durable_tasks(app)
    latest = await app.state.athlete_service.get_latest_athlete_state(user_id=user_id)
    assert replay_results == ()
    assert latest is not None
    assert latest.id == snapshot.id


@pytest.mark.asyncio
async def test_same_user_burst_coalesces_and_cross_user_state_stays_isolated(
    make_app,
    sessions,
    user_id,
    clock,
) -> None:
    """验证：同一用户并发记录多课只合并出一次快照（多余触发 obsolete_noop），另一用户独立产生自己的快照。"""
    other_user = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other_user, created_at=clock.now(), updated_at=clock.now()))
    app = make_app()

    def mutation(distance_m: float) -> WorkoutMutation:
        return WorkoutMutation(
            started_at=clock.now() - timedelta(days=1),
            distance_m=distance_m,
            duration_s=1800,
            avg_heart_rate=140,
            max_heart_rate=155,
            workout_type=WorkoutType.EASY,
            source=WorkoutSource.MANUAL,
        )

    # asyncio.gather：并发原语，同时提交三条记录——同用户两条 + 另一用户一条。
    await asyncio.gather(
        app.state.workout_command_service.record(
            user_id=user_id,
            mutation=mutation(5000),
            event_metadata=EventMetadata(correlation_id=new_id()),
        ),
        app.state.workout_command_service.record(
            user_id=user_id,
            mutation=mutation(6000),
            event_metadata=EventMetadata(correlation_id=new_id()),
        ),
        app.state.workout_command_service.record(
            user_id=other_user,
            mutation=mutation(7000),
            event_metadata=EventMetadata(correlation_id=new_id()),
        ),
    )
    results = await drain_durable_tasks(app)
    assert sum(result.status == "success" for result in results) >= 2
    assert any(result.status == "obsolete_noop" for result in results)

    async with short_session(sessions) as session:
        counts = {
            uid: await session.scalar(
                select(func.count())
                .select_from(AthleteStateSnapshotRow)
                .where(AthleteStateSnapshotRow.user_id == uid)
            )
            for uid in (user_id, other_user)
        }
        snapshots = list((await session.scalars(select(AthleteStateSnapshotRow))).all())
    assert counts == {user_id: 1, other_user: 1}
    assert {snapshot.user_id for snapshot in snapshots} == {user_id, other_user}