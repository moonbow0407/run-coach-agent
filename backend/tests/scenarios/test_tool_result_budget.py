"""Phase 2 必过场景：Tool Result Budget 与 Conversation Boundary。

模拟用户询问未来计划：验证计划 Tool 的窗口与 20 条截断预算，
以及 Tool 交互细节不进入用户可见的会话消息。
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.infrastructure.database.models.coaching import PlannedSessionRow
from app.infrastructure.database.session import short_session
from tests.helpers import load_turn_messages, request_context_for


def _tool_call(tool: str, arguments: dict, call_id: str) -> ToolCallAction:
    """构造脚本中的一步：一次模型 Tool 调用动作。"""
    return ToolCallAction(tool=tool, arguments=arguments, model_call_id=call_id)


@pytest.mark.asyncio
async def test_active_plan_budget_window_and_truncation(
    make_app,
    slice_seed,
    clock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """场景 15：get_active_plan 只返回窗口内课次（上限 20，截断显式），
    WorkingContext 使用同一受控摘要。"""
    # 追加 25 条窗口内课次，触发 20 条硬上限截断。
    async with short_session(sessions, commit=True) as session:
        for i in range(25):
            session.add(
                PlannedSessionRow(
                    id=uuid4(),
                    plan_id=slice_seed.plan_id,
                    scheduled_date=date(2026, 8, 28) + timedelta(days=i % 14),
                    session_type="easy",
                    title=f"补充课次 {i}",
                    prescription={"distance_m": 5000},
                )
            )

    reasoner = ScriptedReasoner(
        [
            _tool_call("search_tools", {"query": "训练计划 课表"}, "call-plan-0"),
            _tool_call("get_active_plan", {}, "call-plan-1"),
            FinalAction(content="课次已截断。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="我接下来的计划是什么？",
    )
    observation = reasoner.seen_contexts[2].state.interactions[3]
    assert observation.status == "success"
    data = observation.data
    assert isinstance(data, dict)
    # 课次不超过 20 条，截断信息显式。
    assert data["truncated"] is True
    assert len(data["sessions"]) == 20
    assert data["window_start"] == "2026-08-24"  # as_of 所在 ISO 周（周五）
    assert data["window_end"] == "2026-09-10"  # as_of 起 14 天

    # WorkingContext 的 active plan 使用同一摘要语义。
    bundle = reasoner.seen_contexts[0].context_bundle
    active_plan = bundle.working_context.active_plan
    assert active_plan is not None
    assert len(active_plan.sessions) <= 20
    assert active_plan.truncated is True
    assert active_plan.window_start.isoformat() == "2026-08-24"


@pytest.mark.asyncio
async def test_conversation_boundary_tool_interactions_not_in_messages(
    make_app,
    slice_seed,
    clock,
    sessions,
) -> None:
    """场景 16：ToolCall / Observation / 搜索记录不进入 messages；
    只有 user / assistant Canonical Message。"""
    workout_id = slice_seed.workout_ids[-1]
    reasoner = ScriptedReasoner(
        [
            _tool_call("search_tools", {"query": "训练详情"}, "call-1"),
            _tool_call("get_workout_detail", {"workout_id": str(workout_id)}, "call-2"),
            FinalAction(content="上次是 8 公里间歇。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    result = await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="上次练了什么",
    )
    messages = await load_turn_messages(sessions, result.turn_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].content == "上次练了什么"
    assert messages[1].content == "上次是 8 公里间歇。"
    # messages 表中不存在任何 Tool 术语残留。
    for message in messages:
        assert "search_tools" not in message.content
        assert "tool_call" not in message.content


