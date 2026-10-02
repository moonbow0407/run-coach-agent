"""Durable Episode trigger 由 Application Service 选择有界 canonical evidence。"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.pool import NullPool

from app.agent.reasoning.scripted import ScriptedReasoner
from app.bootstrap import create_app
from app.coaching.contracts.durable_events import (
    AthleteStateRecomputedV1,
    new_athlete_state_recomputed_event,
)
from app.common.clock import FrozenClock
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import AthleteStateSnapshotRow
from app.infrastructure.database.models.memory import EpisodeEvidenceRow, EpisodeRow
from app.infrastructure.database.session import short_session
from app.infrastructure.outbox.writer import OutboxWriter
from app.infrastructure.seed.vertical_slice import seed_vertical_slice
from app.memory.domain.evidence import EvidenceSourceType
from tests.durable import drain_durable_tasks
from tests.integration.test_memory_vertical_slice import FixedEmbeddingProvider


@pytest.mark.asyncio
async def test_state_triggers_complete_same_fatigue_episode(
    sessions,
    user_id,
    test_settings,
    clock,
) -> None:
    """验证：风险与恢复两次状态快照触发投影进同一疲劳 episode；同一触发重放幂等，不重复记证据。"""
    risk_at = clock.now()
    recovery_at = risk_at + timedelta(days=7)
    risk_id = new_id()
    recovery_id = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(_snapshot(risk_id, user_id, 1, risk_at, "high", "poor"))

    # FixedEmbeddingProvider：固定向量桩（复用自记忆垂直切片测试），保证检索结果可断言。
    first_app = create_app(
        test_settings,
        reasoner=ScriptedReasoner([]),
        clock=FrozenClock(risk_at),
        poolclass=NullPool,
        embedding_provider=FixedEmbeddingProvider(),
    )
    second_app = None
    # 每个时间点单独建 app（时钟冻结在不同时刻），模拟跨天到达的两个触发。
    try:
        first_results = await first_app.state.episode_projection_service.project_trigger(
            user_id=user_id,
            trigger_type=EvidenceSourceType.ATHLETE_STATE_SNAPSHOT,
            trigger_id=risk_id,
            projector_version="phase5.v1",
        )
        assert len(first_results) == 1

        async with short_session(sessions, commit=True) as session:
            session.add(_snapshot(recovery_id, user_id, 2, recovery_at, "low", "good"))
        second_app = create_app(
            test_settings,
            reasoner=ScriptedReasoner([]),
            clock=FrozenClock(recovery_at),
            poolclass=NullPool,
            embedding_provider=FixedEmbeddingProvider(),
        )
        second_results = await second_app.state.episode_projection_service.project_trigger(
            user_id=user_id,
            trigger_type=EvidenceSourceType.ATHLETE_STATE_SNAPSHOT,
            trigger_id=recovery_id,
            projector_version="phase5.v1",
        )
        replay = await second_app.state.episode_projection_service.project_trigger(
            user_id=user_id,
            trigger_type=EvidenceSourceType.ATHLETE_STATE_SNAPSHOT,
            trigger_id=recovery_id,
            projector_version="phase5.v1",
        )
        assert second_results[0].result_ids == first_results[0].result_ids
        assert replay[0].replayed

        async with short_session(sessions) as session:
            episode = await session.scalar(select(EpisodeRow))
            evidence_count = await session.scalar(
                select(func.count()).select_from(EpisodeEvidenceRow)
            )
        assert episode is not None
        # 两个触发共享同一 logical_key（锚定在首个触发），证据补齐至 2 条且 episode completed。
        assert episode.status == "completed"
        assert episode.logical_key == f"fatigue_trigger:{risk_id}"
        assert evidence_count == 2
    finally:
        # teardown：显式释放连接池，避免 NullPool 引擎跨用例残留。
        await first_app.state.engine.dispose()
        if second_app is not None:
            await second_app.state.engine.dispose()


@pytest.mark.asyncio
async def test_confirmed_plan_and_recovery_state_complete_two_stable_episodes(
    sessions,
    test_settings,
    clock,
) -> None:
    """验证：计划确认与恢复快照各自开一个 building episode，恢复事件到达后两集均原地补证据并 completed。"""
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    app = create_app(
        test_settings,
        reasoner=ScriptedReasoner([]),
        clock=clock,
        poolclass=NullPool,
        embedding_provider=FixedEmbeddingProvider(),
    )
    recovery_app = None
    try:
        state = await app.state.athlete_recompute_service.recompute(
            user_id=seed.user_id,
            as_of=clock.now(),
        )
        turn_id = new_id()
        change, _ = await app.state.plan_adaptation_service.propose_reduce_upcoming_load(
            user_id=seed.user_id,
            turn_id=turn_id,
            run_id=new_id(),
            as_of=clock.now(),
            based_on_plan_version=1,
            based_on_state_version=state.version,
            horizon_days=7,
            reason="高疲劳，降低后续负荷",
        )
        await app.state.plan_adaptation_service.promote_draft_for_turn(
            user_id=seed.user_id,
            turn_id=turn_id,
        )
        await app.state.plan_adaptation_service.confirm(
            user_id=seed.user_id,
            plan_change_id=change.id,
            event_metadata=EventMetadata(correlation_id=new_id(), trace_id=new_id()),
        )
        await drain_durable_tasks(app)
        # 此时计划提案已确认、恢复快照未到：应有两个 building 中的 episode。
        async with short_session(sessions) as session:
            building = list(
                (
                    await session.scalars(
                        select(EpisodeRow).where(EpisodeRow.user_id == seed.user_id)
                    )
                ).all()
            )
        assert len(building) == 2
        assert {item.status for item in building} == {"building"}

        recovery_at = clock.now() + timedelta(days=7)
        recovery_id = new_id()
        # 手工补一条 7 天后的恢复快照及其 durable 事件，再由新 app 消费。
        recovery = _snapshot(
            recovery_id,
            seed.user_id,
            state.version + 1,
            recovery_at,
            "low",
            "good",
        )
        event = new_athlete_state_recomputed_event(
            user_id=seed.user_id,
            payload=AthleteStateRecomputedV1(
                snapshot_id=recovery_id,
                snapshot_version=state.version + 1,
                as_of=recovery_at,
                algorithm_version="test.v1",
            ),
            metadata=EventMetadata(correlation_id=new_id(), causation_id=new_id()),
        )
        async with short_session(sessions, commit=True) as session:
            session.add(recovery)
            OutboxWriter().add(session, event)

        recovery_app = create_app(
            test_settings,
            reasoner=ScriptedReasoner([]),
            clock=FrozenClock(recovery_at),
            poolclass=NullPool,
            embedding_provider=FixedEmbeddingProvider(),
        )
        await drain_durable_tasks(recovery_app)
        async with short_session(sessions) as session:
            completed = list(
                (
                    await session.scalars(
                        select(EpisodeRow)
                        .where(EpisodeRow.user_id == seed.user_id)
                        .order_by(EpisodeRow.type)
                    )
                ).all()
            )
            evidence_count = await session.scalar(
                select(func.count())
                .select_from(EpisodeEvidenceRow)
                .where(EpisodeEvidenceRow.user_id == seed.user_id)
            )
        assert len(completed) == 2
        assert {item.status for item in completed} == {"completed"}
        assert {item.logical_key for item in completed} == {
            f"plan_change:{change.id}",
            next(item.logical_key for item in building if item.type == "fatigue_and_recovery"),
        }
        assert evidence_count == 6
    finally:
        await app.state.engine.dispose()
        if recovery_app is not None:
            await recovery_app.state.engine.dispose()

def _snapshot(
    snapshot_id,
    user_id,
    version,
    as_of,
    fatigue,
    recovery,
) -> AthleteStateSnapshotRow:
    """构造一条状态快照行：fatigue/recovery 由参数指定，其余指标取固定可信值。"""
    return AthleteStateSnapshotRow(
        id=snapshot_id,
        user_id=user_id,
        version=version,
        as_of=as_of,
        fatigue_level=fatigue,
        recovery_level=recovery,
        recent_training_load=100.0,
        workout_completion_rate=0.8,
        training_load_coverage=1.0,
        signals=[],
        confidence=0.9,
        algorithm_version="test.v1",
        created_at=as_of,
    )
