"""Eval Harness 集成场景（真实 PostgreSQL，PHASE 6 §23.2）。

覆盖：CONTEXT RunStep 持久化与 user-scoped 读取、跨用户不泄漏、
EvalTrace 重建、纠正经正式 Worker 完成取代、新 Thread 召回、
Context Injection、PlanChange 的 DRAFT → PENDING barrier、
Coaching Grader 的 source identity 绑定、Eval DB 守卫拒绝误连。
"""

from uuid import uuid4
from zlib import crc32

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.run import AgentRunStatus, RunStepKind
from app.agent.reasoning.scripted import ScriptedReasoner
from app.bootstrap import build_container
from app.common.errors import NotFoundError
from app.evals.environment import reset_eval_database
from app.evals.errors import EvalEnvironmentError
from app.evals.graders import grade_coaching_decision
from app.evals.loader import load_cases
from app.evals.models import CoachingExpectation
from app.evals.report import STATUS_PASS
from app.evals.runner import EvalRunner
from app.evals.trace import EvalTrace
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.coaching import PlanChangeRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from app.infrastructure.evals.readers import EvalCoachingStateReader
from app.memory.ports.embedding import EmbeddingBatch
from tests.durable import drain_durable_tasks
from tests.helpers import request_context_for


class HashedTokenEmbedding:
    """字符袋向量桩：共享字符越多相似度越高；crc32 保证跨进程确定。"""

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        return EmbeddingBatch(
            vectors=tuple(self._vector(item) for item in texts),
            model="hashed-token",
            version="1",
            dimensions=1536,
        )

    def _vector(self, value: str) -> tuple[float, ...]:
        raw = [0.0] * 1536
        for char in set(value):
            raw[crc32(char.encode("utf-8")) % 1536] += 1.0
        norm = sum(item * item for item in raw) ** 0.5 or 1.0
        return tuple(item / norm for item in raw)


def _adapt_reasoner() -> ScriptedReasoner:
    """高疲劳正例的脚本轨迹：发现 → 提案 → 最终回答。"""
    return ScriptedReasoner(
        [
            ToolCallAction(
                tool="search_tools",
                arguments={"query": "降低未来训练负荷 计划调整"},
                model_call_id="call-1",
            ),
            ToolCallAction(
                tool="propose_plan_adaptation",
                arguments={
                    "based_on_plan_version": 1,
                    "based_on_state_version": 1,
                    "horizon_days": 7,
                    "reason": "高疲劳且未来窗口含节奏课，建议降负荷",
                },
                model_call_id="call-2",
            ),
            FinalAction(content="已生成降负荷草案，等待你确认。"),
        ]
    )


@pytest.fixture(autouse=True)
async def _clean_db(engine: AsyncEngine):
    """模块内每个测试前后都清库：Runner 自建容器，不复用 clean_tables 的会话。"""
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    yield
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


async def test_context_runstep_persisted_and_user_scoped(make_app, slice_seed) -> None:
    """场景 1：CONTEXT RunStep 被持久化，且能经 user-scoped TraceReader 读取。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="好的。")]))
    context = request_context_for(slice_seed.user_id, app.state.clock)
    result = await app.state.chat_service.send_message(
        request_context=context, thread_id=None, content="看看最近的训练"
    )
    steps = await app.state.trace_reader.list_steps(
        user_id=slice_seed.user_id, run_id=result.run_id
    )
    kinds = [step.kind for step in steps]
    assert kinds[0] is RunStepKind.CONTEXT
    assert kinds[-1] is RunStepKind.FINAL
    manifest = steps[0].input_data
    assert manifest["plan_id"] == str(slice_seed.plan_id)
    assert "semantic_memory_ids" in manifest
    await app.state.engine.dispose()


async def test_cross_user_run_read_not_leaked(make_app, slice_seed) -> None:
    """场景 2：跨用户读取 run 统一 not-found，不泄漏存在性。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="好的。")]))
    context = request_context_for(slice_seed.user_id, app.state.clock)
    result = await app.state.chat_service.send_message(
        request_context=context, thread_id=None, content="看看最近的训练"
    )
    with pytest.raises(NotFoundError):
        await app.state.trace_reader.list_steps(user_id=uuid4(), run_id=result.run_id)
    await app.state.engine.dispose()


async def test_scripted_tool_trace_rebuilt_by_eval_trace(make_app, slice_seed) -> None:
    """场景 3：Scripted 工具轨迹可由 EvalTrace 可靠重建。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="search_tools",
                arguments={"query": "训练记录"},
                model_call_id="call-1",
            ),
            ToolCallAction(
                tool="get_recent_workouts",
                arguments={"days": 7},
                model_call_id="call-2",
            ),
            FinalAction(content="这是你最近的训练。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, app.state.clock)
    result = await app.state.chat_service.send_message(
        request_context=context, thread_id=None, content="看看最近 7 天训练"
    )
    steps = await app.state.trace_reader.list_steps(
        user_id=slice_seed.user_id, run_id=result.run_id
    )
    trace = EvalTrace(steps, run_status=AgentRunStatus.COMPLETED)
    assert [call.tool for call in trace.attempted_tool_calls] == [
        "search_tools",
        "get_recent_workouts",
    ]
    assert "get_recent_workouts" in trace.successful_tools()
    # search_tools 只报告"新发现"的隐藏工具；always-on 工具不会出现在 hits。
    assert "get_workout_detail" in trace.search_hits()
    assert trace.search_hit_step_indexes("get_recent_workouts") == ()
    # 轨迹顺序：context → reasoning → call → obs → …；get_recent_workouts 的成功 obs 在 7。
    assert trace.success_observation_index("get_recent_workouts") == 7
    assert trace.final_answer == "这是你最近的训练。"
    await app.state.engine.dispose()


async def test_memory_conflict_case_passes_end_to_end(test_settings) -> None:
    """场景 4+5：纠正经 Outbox / in-process Worker 完成取代；新 Thread 只召新记忆。"""
    case = load_cases(case_id="memory_conflict_schedule_001")[0]
    report = await EvalRunner(
        test_settings, embedding_provider=HashedTokenEmbedding()
    ).run([case], trials=1)
    assert report.case_results[0].status == STATUS_PASS


async def test_memory_retrieval_and_injection_cases_pass(test_settings) -> None:
    """场景 6：目标记忆真实进入检索结果与 CONTEXT RunStep。

    字符袋桩向量的相似度区分度有限，forbidden 排除交给真实 embedding 的
    手动验收；这里断言场景本意——required 目标被检索并注入。
    """
    by_id = {case.id: case for case in load_cases(suite="memory")}
    report = await EvalRunner(test_settings, embedding_provider=HashedTokenEmbedding()).run(
        [by_id["memory_semantic_recall_001"], by_id["memory_context_injection_001"]],
        trials=1,
    )
    recall = next(case for case in report.case_results if case.case_id == "memory_semantic_recall_001")
    grader = next(
        item for item in recall.trials[0].grader_results if item["grader"] == "semantic_recall"
    )
    assert grader["details"]["missing_required"] == []
    injection = next(
        case for case in report.case_results if case.case_id == "memory_context_injection_001"
    )
    assert injection.status == STATUS_PASS
    manifest = injection.trials[0].turns[0].context_manifest
    assert manifest["memory_policy_version"] == "phase4.v1"
    assert len(manifest["semantic_memory_ids"]) > 0


async def test_plan_change_draft_until_barrier_drained(make_app, slice_seed, sessions) -> None:
    """场景 7：ChatService 返回后 PlanChange 仍为 DRAFT，drain 后才进入 PENDING。"""
    # v1 降负荷前提要求 HIGH 疲劳或 POOR 恢复：把 seed 快照调到 high。
    from app.infrastructure.database.models.coaching import AthleteStateSnapshotRow

    async with short_session(sessions, commit=True) as session:
        row = (
            await session.scalars(
                select(AthleteStateSnapshotRow).where(
                    AthleteStateSnapshotRow.user_id == slice_seed.user_id
                )
            )
        ).one()
        row.fatigue_level = "high"
    app = make_app(reasoner=_adapt_reasoner())
    context = request_context_for(slice_seed.user_id, app.state.clock)
    result = await app.state.chat_service.send_message(
        request_context=context, thread_id=None, content="太累了，帮我调整计划"
    )
    async with short_session(app.state.sessions) as session:
        row = (
            await session.scalars(
                select(PlanChangeRow).where(PlanChangeRow.user_id == slice_seed.user_id)
            )
        ).one()
        assert row.status == "draft"
        assert row.source_turn_id == result.turn_id
        assert row.source_run_id == result.run_id
    await drain_durable_tasks(app)
    async with short_session(app.state.sessions) as session:
        row = (
            await session.scalars(
                select(PlanChangeRow).where(PlanChangeRow.user_id == slice_seed.user_id)
            )
        ).one()
        assert row.status == "pending_confirmation"
    await app.state.engine.dispose()


async def test_runner_coaching_positive_and_source_identity(test_settings) -> None:
    """场景 8：Runner 正例 PASS；Grader 只认当前 source turn/run 的提案。"""
    case = load_cases(case_id="coaching_adapt_001")[0]
    report = await EvalRunner(
        test_settings,
        embedding_provider=HashedTokenEmbedding(),
        reasoner=_adapt_reasoner(),
    ).run([case], trials=1)
    assert report.case_results[0].status == STATUS_PASS

    # 用只读容器取回 Runner 创建的用户，再补一条"别的轮次"的提案：
    # 评分锚定当前 turn/run 时必须只命中本轮提案（sourced_count==1）。
    container = build_container(test_settings, poolclass=NullPool)
    try:
        async with short_session(container.sessions) as session:
            user_id = (await session.scalars(select(UserRow.id).limit(1))).one()
        reader = EvalCoachingStateReader(container.sessions)
        changes = await reader.list_plan_changes(user_id=user_id)
        assert len(changes) == 1
        active = await reader.get_active_plan(user_id=user_id)
        results = grade_coaching_decision(
            CoachingExpectation(must_create_plan_change=True),
            plan_changes=changes,
            active_plan=active,
            fixture_plan_id=changes[0].from_plan_id,
            fixture_plan_version=1,
            fixture_state_version=1,
            turn_id=uuid4(),  # 陌生 turn：source identity 不匹配
            run_id=uuid4(),
        )
        created = next(item for item in results if item.grader == "coaching_plan_change_created")
        assert not created.passed
        assert created.details["sourced_count"] == 0
    finally:
        await container.engine.dispose()


async def test_reset_refuses_non_eval_database(engine: AsyncEngine) -> None:
    """场景 9：非 run_coach_eval 连接上绝不执行 TRUNCATE。"""
    with pytest.raises(EvalEnvironmentError):
        await reset_eval_database(engine)
