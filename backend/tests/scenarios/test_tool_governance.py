"""Tool 可信上下文与错误治理的集成测试。

覆盖 Phase 2 必过场景：Hidden Tool Guess、Validation 矩阵、
Trusted Context（身份注入 / 跨用户隔离）、Timeout 与
Runtime 不变量破坏（Session run_id 不一致使 AgentRun failed）。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.lifecycle.events import TurnFailed
from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.common.clock import FrozenClock
from app.common.errors import ToolRuntimeError
from app.infrastructure.database.models.coaching import WorkoutRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from tests.helpers import event_types, record_events, request_context_for


@pytest.mark.asyncio
async def test_hidden_tool_guess_returns_tool_not_available(
    make_app,
    slice_seed,
    clock,
    sessions,
) -> None:
    """场景 2（前半）：Reasoner 直接猜测隐藏 Tool 得 tool_not_available。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="get_workout_feedback",
                arguments={"workout_id": str(slice_seed.workout_ids[-1])},
                model_call_id="call-guess-1",
            ),
            FinalAction(content="无法读取反馈。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    result = await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="读取上次训练的主观反馈",
    )
    assert result.content == "无法读取反馈。"
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "tool_not_available"

@pytest.mark.asyncio
async def test_unregistered_tool_returns_tool_not_found(
    make_app,
    slice_seed,
    clock,
) -> None:
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="get_nonexistent_tool",
                arguments={},
                model_call_id="call-missing-1",
            ),
            FinalAction(content="工具不存在。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="随便试试",
    )
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "tool_not_found"

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},  # 缺字段
        {"days": 14, "extra": 1},  # 多字段
        {"days": "14"},  # 类型错误
        {"days": 0},  # 越界（下限）
        {"days": 366},  # 越界（上限）
    ],
)
async def test_invalid_arguments_matrix(
    make_app,
    slice_seed,
    clock,
    arguments: dict,
) -> None:
    """场景 8：缺字段 / 多字段 / 类型错 / 越界统一 invalid_arguments。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="get_recent_workouts",
                arguments=arguments,
                model_call_id="call-invalid-1",
            ),
            FinalAction(content="参数不合法。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="最近的训练",
    )
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "invalid_arguments"

@pytest.mark.asyncio
@pytest.mark.parametrize("identity_field", ["user_id", "userId", "run_id", "thread_id"])
async def test_identity_injection_rejected(
    make_app,
    slice_seed,
    clock,
    identity_field: str,
) -> None:
    """场景 9：参数注入身份字段被 extra=forbid 拒绝，返回 invalid_arguments。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="get_recent_workouts",
                arguments={"days": 14, identity_field: str(uuid4())},
                model_call_id="call-inject-1",
            ),
            FinalAction(content="被拒绝。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="读取训练",
    )
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "invalid_arguments"

@pytest.mark.asyncio
async def test_cross_user_workout_detail_not_accessible(
    make_app,
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    slice_seed,
) -> None:
    """场景 9：跨用户 workout detail / feedback 不可访问（返回 None）。"""
    now = clock.now()
    other_user = uuid4()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other_user, created_at=now, updated_at=now))
        await session.flush()
        # 其他用户的训练记录。
        session.add(
            WorkoutRow(
                id=uuid4(),
                user_id=other_user,
                started_at=datetime(2026, 8, 26, 6, 0, tzinfo=UTC),
                distance_m=10000,
                duration_s=3000,
                avg_heart_rate=150,
                max_heart_rate=160,
                workout_type="tempo",
                source="manual",
                created_at=now,
            )
        )
    # 用目标用户身份尝试读取其他用户的 workout（这里用 seed 用户读别人的 ID）。
    other_workout_id = (
        await _get_other_user_workout_id(sessions, other_user)
    )
    reasoner = ScriptedReasoner(
        [
            # 先发现工具（get_workout_detail 为隐藏工具）。
            ToolCallAction(
                tool="search_tools",
                arguments={"query": "训练详情"},
                model_call_id="call-cross-0",
            ),
            ToolCallAction(
                tool="get_workout_detail",
                arguments={"workout_id": str(other_workout_id)},
                model_call_id="call-cross-1",
            ),
            FinalAction(content="查不到。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="读取那条训练",
    )
    observation = reasoner.seen_contexts[2].state.interactions[3]
    assert observation.status == "success"
    # 跨用户读取返回 None（数据不存在于当前用户视角），不泄漏他人数据。
    assert observation.data is None

async def _get_other_user_workout_id(
    sessions: async_sessionmaker[AsyncSession], user_id: UUID
) -> UUID:
    from sqlalchemy import select

    async with short_session(sessions) as session:
        row = (
            await session.scalars(
                select(WorkoutRow).where(WorkoutRow.user_id == user_id)
            )
        ).first()
        assert row is not None
        return row.id

@pytest.mark.asyncio
async def test_session_run_id_mismatch_fails_agent_run(
    make_app,
    slice_seed,
    clock,
    monkeypatch,
) -> None:
    """场景 10：ToolSession 与 run_id 不一致属于 Runtime 不变量破坏，AgentRun failed。"""

    class MismatchedSessionReasoner:
        def __init__(self) -> None:
            self.count = 0

        async def reason(self, context):
            self.count += 1
            if self.count == 1:
                return ToolCallAction(
                    tool="get_recent_workouts",
                    arguments={"days": 7},
                    model_call_id="call-mismatch-1",
                )
            return FinalAction(content="不应到达")

    app = make_app(reasoner=MismatchedSessionReasoner())
    events = record_events(app.state.lifecycle)

    original_create = app.state.tool_runtime.create_session

    def create_mismatched_session(*, run_id):
        session = original_create(run_id=uuid4())  # 错误的 run_id
        return session

    monkeypatch.setattr(app.state.tool_runtime, "create_session", create_mismatched_session)
    context = request_context_for(slice_seed.user_id, clock)
    with pytest.raises(ToolRuntimeError):
        await app.state.chat_service.send_message(
            request_context=context,
            thread_id=None,
            content="触发不一致",
        )
    assert "TurnCommitted" not in event_types(events)
    assert any(isinstance(event, TurnFailed) for event in events)

@pytest.mark.asyncio
async def test_tool_timeout_returns_tool_timeout_observation(
    make_app,
    slice_seed,
    clock,
) -> None:
    """场景 10：Tool 超时返回 tool_timeout Observation，Reasoner 可继续推理。"""
    import asyncio

    from pydantic import BaseModel, ConfigDict

    from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource

    class SlowProbeArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class SlowProbeTool:
        """超时探测工具：执行体长时间睡眠，超时由 Executor 统一截断。"""

        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="slow_probe",
                description="仅用于超时测试的探测工具。",
                tags=("probe",),
                search_hint="probe",
                always_on=True,
                risk=ToolRisk.READ_ONLY,
                source=ToolSource.SYSTEM,
                timeout_s=0.05,
            )

        @property
        def args_model(self) -> type[SlowProbeArgs]:
            return SlowProbeArgs

        async def execute(self, *, args, context):
            await asyncio.sleep(10)
            return {}

    reasoner = ScriptedReasoner(
        [
            ToolCallAction(tool="slow_probe", arguments={}, model_call_id="call-timeout-1"),
            FinalAction(content="工具超时了。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    # 每个 app 持有独立 Registry，注册探测工具不会污染其他测试。
    app.state.tool_registry.register(SlowProbeTool())
    context = request_context_for(slice_seed.user_id, clock)
    result = await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="慢工具",
    )
    assert result.content == "工具超时了。"
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "tool_timeout"
