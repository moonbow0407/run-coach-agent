"""记忆链路端到端：Turn 提交→语义记忆投影→新轮次检索；失败拦截、用户隔离、episode 补全与双时态纠正。"""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.pool import NullPool

from app.agent.models.action import FinalAction
from app.agent.models.message import Message
from app.agent.reasoning.scripted import FailingReasoner, ScriptedReasoner
from app.bootstrap import create_app
from app.common.clock import FrozenClock
from app.infrastructure.database.models.coaching import AthleteStateSnapshotRow
from app.infrastructure.database.models.memory import (
    EpisodeEvidenceRow,
    EpisodeRow,
    MemoryEvidenceRow,
    MemoryProjectionRunRow,
    SemanticMemoryRow,
)
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from app.memory.domain.episode import EpisodeType
from app.memory.domain.evidence import EvidenceSourceType
from app.memory.domain.semantic import MemoryOrigin, SemanticMemoryType
from app.memory.ports.embedding import EmbeddingBatch
from app.memory.ports.extractor import ExtractedSemanticCandidate
from tests.conftest import token_for
from tests.durable import drain_durable_tasks


class ExplicitConstraintExtractor:
    """桩抽取器：仅当用户消息含"周三晚上"时产出一条显式可用性约束候选。"""

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]:
        if "周三晚上" not in user_message.content:
            return ()
        return (
            ExtractedSemanticCandidate(
                type=SemanticMemoryType.AVAILABILITY_CONSTRAINT,
                origin=MemoryOrigin.EXPLICIT,
                subject_key="weekly:wednesday:evening",
                value=False,
                content="用户周三晚上长期无法训练",
                valid_from=committed_at,
                valid_until=None,
            ),
        )


class FixedEmbeddingProvider:
    """嵌入桩：所有文本都映射到同一个 1536 维固定向量，使相似检索结果确定可断言。"""

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        vector = (1.0,) + (0.0,) * 1535
        return EmbeddingBatch(
            vectors=tuple(vector for _ in texts),
            model="test-embedding",
            version="1",
            dimensions=1536,
        )


class PreferenceExtractor:
    """桩抽取器：从消息中识别"晚上/早上"训练偏好，产出日程偏好候选。"""

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]:
        value = "evening" if "晚上" in user_message.content else "morning" if "早上" in user_message.content else None
        if value is None:
            return ()
        return (
            ExtractedSemanticCandidate(
                type=SemanticMemoryType.SCHEDULE_PREFERENCE,
                origin=MemoryOrigin.EXPLICIT,
                subject_key="preferred_training_time",
                value=value,
                content=f"用户长期更喜欢{'晚上' if value == 'evening' else '早上'}训练",
                valid_from=committed_at,
                valid_until=None,
            ),
        )


@pytest.mark.asyncio
async def test_committed_turn_projects_and_new_thread_retrieves_memory(
    make_app,
    sessions,
    user_id,
    test_settings,
    clock,
) -> None:
    """验证：Turn 提交后语义记忆投影落库，下一轮对话能检索到；同一 Turn 重复投影按 receipt 幂等。"""
    reasoner = ScriptedReasoner(
        [
            FinalAction(content="记住了，之后会避开这个时段。"),
            FinalAction(content="我会结合你的长期安排建议。"),
        ]
    )
    app = make_app(
        reasoner=reasoner,
        memory_extractor=ExplicitConstraintExtractor(),
        embedding_provider=FixedEmbeddingProvider(),
    )
    headers = {"Authorization": f"Bearer {token_for(user_id, test_settings, clock)}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/v1/chat",
            json={"message": "以后周三晚上不要给我排训练，我有课。"},
            headers=headers,
        )
        await drain_durable_tasks(app)
        # drain_durable_tasks：同步驱动 outbox→消费链路；再手动重投影一次验证幂等。
        replay = await app.state.semantic_memory_projection_service.project_committed_turn(
            user_id=user_id,
            turn_id=UUID(first.json()["turn_id"]),
            projector_version="phase4.v1",
        )
        second = await client.post(
            "/api/v1/chat",
            json={"message": "帮我看看下周怎么安排。"},
            headers=headers,
        )
        await drain_durable_tasks(app)

    assert first.status_code == 200
    # replayed=True：第二次投影识别出 receipt 已存在，未重复入库。
    assert replay.replayed
    assert second.status_code == 200
    bundle = reasoner.seen_contexts[1].context_bundle
    assert bundle.current_input == "帮我看看下周怎么安排。"
    assert [item.content for item in bundle.semantic_memories] == ["用户周三晚上长期无法训练"]
    assert bundle.semantic_memories[0].origin == "explicit"

    async with short_session(sessions) as session:
        memories = list((await session.scalars(select(SemanticMemoryRow))).all())
        evidence_count = await session.scalar(select(func.count()).select_from(MemoryEvidenceRow))
        receipt_count = await session.scalar(
            select(func.count()).select_from(MemoryProjectionRunRow)
        )
    assert len(memories) == 1
    assert memories[0].status == "active"
    assert evidence_count == 2
    assert receipt_count == 2  # 第二个 Turn 合法地记录“没有候选”。


@pytest.mark.asyncio
async def test_failed_turn_cannot_create_projection_receipt(
    make_app,
    sessions,
    user_id,
    test_settings,
    clock,
) -> None:
    """验证：失败 Turn 不产生任何投影 receipt——失败的对话不能留下记忆痕迹。"""
    app = make_app(
        reasoner=FailingReasoner(),
        memory_extractor=ExplicitConstraintExtractor(),
        embedding_provider=FixedEmbeddingProvider(),
    )
    headers = {"Authorization": f"Bearer {token_for(user_id, test_settings, clock)}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "以后周三晚上不要给我排训练，我有课。"},
            headers=headers,
        )
    assert response.status_code == 500
    async with short_session(sessions) as session:
        count = await session.scalar(select(func.count()).select_from(MemoryProjectionRunRow))
    assert count == 0


@pytest.mark.asyncio
async def test_same_vectors_remain_cross_user_isolated(
    make_app,
    sessions,
    user_id,
    test_settings,
    clock,
) -> None:
    """验证：两个用户的记忆向量完全相同（固定向量桩），检索仍按用户隔离、互不串扰。"""
    other_user_id = uuid4()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other_user_id, created_at=clock.now(), updated_at=clock.now()))
    reasoner = ScriptedReasoner([FinalAction(content="收到。") for _ in range(4)])
    app = make_app(
        reasoner=reasoner,
        memory_extractor=PreferenceExtractor(),
        embedding_provider=FixedEmbeddingProvider(),
    )
    headers_a = {"Authorization": f"Bearer {token_for(user_id, test_settings, clock)}"}
    headers_b = {
        "Authorization": f"Bearer {token_for(other_user_id, test_settings, clock)}"
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/chat", json={"message": "我长期更喜欢晚上训练。"}, headers=headers_a
        )
        await drain_durable_tasks(app)
        await client.post(
            "/api/v1/chat", json={"message": "我长期更喜欢早上训练。"}, headers=headers_b
        )
        await drain_durable_tasks(app)
        await client.post(
            "/api/v1/chat", json={"message": "下周怎么安排？"}, headers=headers_a
        )
        await client.post(
            "/api/v1/chat", json={"message": "下周怎么安排？"}, headers=headers_b
        )
    memory_a = [item.content for item in reasoner.seen_contexts[2].context_bundle.semantic_memories]
    memory_b = [item.content for item in reasoner.seen_contexts[3].context_bundle.semantic_memories]
    assert memory_a == ["用户长期更喜欢晚上训练"]
    assert memory_b == ["用户长期更喜欢早上训练"]


@pytest.mark.asyncio
async def test_fatigue_episode_building_completes_in_place_and_old_window_is_obsolete(
    make_app,
    sessions,
    user_id,
    clock,
) -> None:
    """验证：疲劳窗口先建 building，补齐结局证据后原地 completed；缺失结局的过期窗口重投影标记 obsolete。"""
    trigger_id = uuid4()
    outcome_id = uuid4()
    trigger_at = clock.now() - timedelta(days=7)
    outcome_at = clock.now()
    async with short_session(sessions, commit=True) as session:
        session.add_all(
            [
                _snapshot(trigger_id, user_id, 1, trigger_at, "high", "poor"),
                _snapshot(outcome_id, user_id, 2, outcome_at, "low", "good"),
            ]
        )
    app = make_app(
        reasoner=ScriptedReasoner([]),
        embedding_provider=FixedEmbeddingProvider(),
    )
    service = app.state.episode_projection_service
    first = await service.project_window(
        user_id=user_id,
        type=EpisodeType.FATIGUE_AND_RECOVERY,
        started_at=trigger_at,
        ended_at=outcome_at,
        source_ids=((EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, trigger_id),),
        projector_version="phase4.v1",
    )
    second = await service.project_window(
        user_id=user_id,
        type=EpisodeType.FATIGUE_AND_RECOVERY,
        started_at=trigger_at,
        ended_at=outcome_at,
        source_ids=(
            (EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, trigger_id),
            (EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, outcome_id),
        ),
        projector_version="phase4.v1",
    )
    obsolete = await service.project_window(
        user_id=user_id,
        type=EpisodeType.FATIGUE_AND_RECOVERY,
        started_at=trigger_at,
        ended_at=outcome_at,
        source_ids=((EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, trigger_id),),
        projector_version="phase4.v1",
    )
    assert first.result_ids == second.result_ids
    assert obsolete.obsolete
    async with short_session(sessions) as session:
        episode = await session.scalar(select(EpisodeRow))
        evidence_count = await session.scalar(select(func.count()).select_from(EpisodeEvidenceRow))
    assert episode is not None and episode.status == "completed"
    assert evidence_count == 2


def _snapshot(
    snapshot_id: UUID,
    user_id: UUID,
    version: int,
    as_of: datetime,
    fatigue: str,
    recovery: str,
) -> AthleteStateSnapshotRow:
    """构造状态快照行：fatigue/recovery 由参数给定，其余指标取固定可信值。"""
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


@pytest.mark.asyncio
async def test_explicit_correction_supersedes_but_historical_as_of_keeps_old_knowledge(
    sessions,
    user_id,
    test_settings,
    clock,
) -> None:
    """验证：显式纠正使旧偏好 superseded、新偏好 active；按历史 as_of 检索仍得旧知识（双时态语义）。"""
    first_at = clock.now()
    correction_at = first_at + timedelta(days=1)
    query_at = correction_at + timedelta(days=1)
    apps = []
    # 三个时钟冻结在不同日期的 app：首报偏好→纠正偏好→检索验证。
    try:
        first_reasoner = ScriptedReasoner([FinalAction(content="收到。")])
        first_app = create_app(
            test_settings,
            reasoner=first_reasoner,
            clock=FrozenClock(first_at),
            poolclass=NullPool,
            memory_extractor=PreferenceExtractor(),
            embedding_provider=FixedEmbeddingProvider(),
        )
        apps.append(first_app)
        headers = {"Authorization": f"Bearer {token_for(user_id, test_settings)}"}
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/chat",
                json={"message": "我长期更喜欢晚上训练。"},
                headers=headers,
            )
            await drain_durable_tasks(first_app)

        correction_reasoner = ScriptedReasoner([FinalAction(content="已按你的纠正更新。")])
        correction_app = create_app(
            test_settings,
            reasoner=correction_reasoner,
            clock=FrozenClock(correction_at),
            poolclass=NullPool,
            memory_extractor=PreferenceExtractor(),
            embedding_provider=FixedEmbeddingProvider(),
        )
        apps.append(correction_app)
        async with AsyncClient(
            transport=ASGITransport(app=correction_app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/chat",
                json={"message": "不是，我现在更喜欢早上训练。"},
                headers=headers,
            )
            await drain_durable_tasks(correction_app)
        # 纠正轮的上下文里应仍能检索到旧偏好（纠正前它是 active 知识）。
        correction_bundle = correction_reasoner.seen_contexts[0].context_bundle
        assert correction_bundle.current_input == "不是，我现在更喜欢早上训练。"
        assert [item.content for item in correction_bundle.semantic_memories] == [
            "用户长期更喜欢晚上训练"
        ]

        current = await correction_app.state.memory_retrieval_service.retrieve(
            user_id=user_id,
            query="训练时间偏好",
            as_of=query_at,
        )
        historical = await correction_app.state.memory_retrieval_service.retrieve(
            user_id=user_id,
            query="训练时间偏好",
            as_of=first_at + timedelta(hours=12),
        )
        # 同一检索查询两个 as_of：现在得到新偏好，历史时点得到旧偏好。
        assert [item.content for item in current.semantic] == ["用户长期更喜欢早上训练"]
        assert [item.content for item in historical.semantic] == ["用户长期更喜欢晚上训练"]
        async with short_session(sessions) as session:
            rows = list(
                (
                    await session.scalars(
                        select(SemanticMemoryRow).order_by(SemanticMemoryRow.created_at)
                    )
                ).all()
            )
        assert [row.status for row in rows] == ["superseded", "active"]
        assert rows[0].superseded_by_id == rows[1].id
    finally:
        # teardown：释放本用例创建的所有引擎连接池。
        for app in apps:
            await app.state.engine.dispose()
