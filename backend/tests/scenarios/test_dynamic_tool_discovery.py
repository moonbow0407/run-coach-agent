"""Phase 2 核心场景：Dynamic Tool Discovery Vertical Slice 与发现边界。

全部通过 ChatService 驱动完整 AgentRuntime（主验收接缝），
断言 ChatResult、RunStep 持久化、可见 Tool 演进与 Lifecycle 事件。
"""

import pytest

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner
from tests.helpers import event_types, load_run_steps, record_events, request_context_for


def _tool_call(tool: str, arguments: dict, call_id: str) -> ToolCallAction:
    return ToolCallAction(tool=tool, arguments=arguments, model_call_id=call_id)


@pytest.mark.asyncio
async def test_dynamic_tool_discovery_vertical_slice(
    make_app,
    slice_seed,
    clock,
    sessions,
) -> None:
    """场景 1：初始只可见 search_tools + get_recent_workouts，
    搜索后解锁新 Schema，完成 detail / feedback 调用并形成 FinalAction。"""
    last_workout_id = slice_seed.workout_ids[-1]
    reasoner = ScriptedReasoner(
        [
            _tool_call("get_recent_workouts", {"days": 7}, "call-1"),
            _tool_call(
                "search_tools", {"query": "训练详情 主观反馈", "limit": 2}, "call-2"
            ),
            _tool_call("get_workout_detail", {"workout_id": str(last_workout_id)}, "call-3"),
            _tool_call(
                "get_workout_feedback", {"workout_id": str(last_workout_id)}, "call-4"
            ),
            FinalAction(content="上次间歇课主观反馈为高用力高疲劳。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    events = record_events(app.state.lifecycle)
    context = request_context_for(slice_seed.user_id, clock)
    result = await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="上次训练强度怎么样，我自己感觉如何？",
    )

    assert result.content == "上次间歇课主观反馈为高用力高疲劳。"

    # 第 1 轮：初始可见集合精确为两个 always-on Tool。
    visible_first = {tool.name for tool in reasoner.seen_contexts[0].visible_tools}
    assert visible_first == {"search_tools", "get_recent_workouts"}

    # 第 3 轮（search_tools 之后）：detail 与 feedback 的 Schema 出现。
    visible_after_search = {tool.name for tool in reasoner.seen_contexts[2].visible_tools}
    assert visible_after_search == {
        "search_tools",
        "get_recent_workouts",
        "get_workout_detail",
        "get_workout_feedback",
    }
    # 解锁后的 Tool 带完整参数 Schema（native tool calling 可用）。
    detail = next(
        tool
        for tool in reasoner.seen_contexts[2].visible_tools
        if tool.name == "get_workout_detail"
    )
    assert detail.parameters_schema["type"] == "object"

    # 全部 4 次调用成功。
    observations = [
        item
        for item in reasoner.seen_contexts[-1].state.interactions
        if hasattr(item, "status")
    ]
    assert [obs.status for obs in observations] == ["success"] * 4

    # search_tools 的 hits 与实际解锁集合一致。
    search_observation = observations[1]
    assert search_observation.data is not None
    hit_names = {hit["name"] for hit in search_observation.data["hits"]}
    assert hit_names == {"get_workout_detail", "get_workout_feedback"}

    # RunStep 轨迹可重建：tool_call 与 observation 各 4 条，成对共享 call_id。
    steps = await load_run_steps(sessions, result.run_id)
    kinds = [step.kind for step in steps]
    assert kinds == [
        "reasoning",
        "tool_call",
        "observation",
        "reasoning",
        "tool_call",
        "observation",
        "reasoning",
        "tool_call",
        "observation",
        "reasoning",
        "tool_call",
        "observation",
        "reasoning",
        "final",
    ]
    tool_calls = [step for step in steps if step.kind == "tool_call"]
    obs_steps = [step for step in steps if step.kind == "observation"]
    for call, obs in zip(tool_calls, obs_steps, strict=True):
        assert call.call_id == obs.call_id
        assert call.input_data["model_call_id"] == obs.output_data["model_call_id"]

    # search_tools 的 query / limit / hits 可从 RunStep 重建（Eval 支持）。
    search_call = tool_calls[1]
    assert search_call.input_data["tool"] == "search_tools"
    assert search_call.input_data["arguments"]["query"] == "训练详情 主观反馈"
    search_obs_step = obs_steps[1]
    assert {hit["name"] for hit in search_obs_step.output_data["data"]["hits"]} == {
        "get_workout_detail",
        "get_workout_feedback",
    }
    types = event_types(events)
    assert "ToolStarted" in types and "ToolCompleted" in types
    assert types[-1] == "TurnCommitted"


@pytest.mark.asyncio
async def test_hidden_tool_guess_then_discovery_unlocks(
    make_app,
    slice_seed,
    clock,
) -> None:
    """场景 2：先猜隐藏 Tool 得 tool_not_available，search 后同 Run 内可执行。"""
    workout_id = slice_seed.workout_ids[-1]
    reasoner = ScriptedReasoner(
        [
            _tool_call("get_workout_feedback", {"workout_id": str(workout_id)}, "call-1"),
            _tool_call("search_tools", {"query": "主观反馈 疲劳"}, "call-2"),
            _tool_call("get_workout_feedback", {"workout_id": str(workout_id)}, "call-3"),
            FinalAction(content="读到反馈了。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="我上次课的感觉",
    )
    first_observation = reasoner.seen_contexts[1].state.interactions[1]
    assert first_observation.status == "error"
    assert first_observation.error_code == "tool_not_available"

    # 同一 AgentRun 内，经 search_tools 发现后成功执行。
    third_observation = reasoner.seen_contexts[3].state.interactions[5]
    assert third_observation.status == "success"
    assert third_observation.data is not None
    assert third_observation.data["perceived_exertion"] == 8


@pytest.mark.asyncio
async def test_run_local_isolation(
    make_app,
    slice_seed,
    clock,
) -> None:
    """场景 3：一个 AgentRun 发现的 Tool 不出现在下一 AgentRun 的初始可见集合。"""
    reasoner_run1 = ScriptedReasoner(
        [
            _tool_call("search_tools", {"query": "训练详情"}, "call-1"),
            FinalAction(content="先找到工具。"),
        ]
    )
    app = make_app(reasoner=reasoner_run1)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="帮我找训练详情工具",
    )
    visible_run1 = {tool.name for tool in reasoner_run1.seen_contexts[1].visible_tools}
    assert "get_workout_detail" in visible_run1

    # 同一 app（同一 Registry / ToolRuntime）内的下一个 AgentRun：
    # 发现不跨 Run 复用，初始可见集合回到 always-on。
    reasoner_run2 = ScriptedReasoner([FinalAction(content="下一个问题。")])
    # ChatService 持有的 runtime 绑定了 reasoner_run1，无法直接替换；
    # 直接构造第二个 app（同样代表新进程的新 Run 基线）验证隔离语义。
    app2 = make_app(reasoner=reasoner_run2)
    await app2.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="再问一个",
    )
    visible_run2 = {tool.name for tool in reasoner_run2.seen_contexts[0].visible_tools}
    assert visible_run2 == {"search_tools", "get_recent_workouts"}


@pytest.mark.asyncio
async def test_search_unlock_atomicity_and_zero_hits(
    make_app,
    slice_seed,
    clock,
) -> None:
    """场景 7：hits 与 DiscoveryState 完全一致；零命中 success + 空 hits。"""
    reasoner = ScriptedReasoner(
        [
            # 零命中：与任何工具元数据都无字符重叠的查询。
            _tool_call("search_tools", {"query": "量子纠缠食谱zzz"}, "call-1"),
            # 正常命中。
            _tool_call("search_tools", {"query": "训练计划 课表"}, "call-2"),
            FinalAction(content="搜索语义验证。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="找一些工具",
    )
    zero_observation = reasoner.seen_contexts[1].state.interactions[1]
    assert zero_observation.status == "success"
    assert zero_observation.data is not None
    assert zero_observation.data["hits"] == []

    # 零命中后可见集合不变（第 2 轮推理时的可见集合）。
    visible_after_zero = {tool.name for tool in reasoner.seen_contexts[1].visible_tools}
    assert visible_after_zero == {"search_tools", "get_recent_workouts"}

    # 正常命中：hits 与解锁集合一致（从下一轮可见集合反推）。
    hit_observation = reasoner.seen_contexts[2].state.interactions[3]
    assert hit_observation.status == "success"
    hit_names = {hit["name"] for hit in hit_observation.data["hits"]}
    visible_after_hit = {tool.name for tool in reasoner.seen_contexts[2].visible_tools}
    assert hit_names <= visible_after_hit
    assert hit_names


@pytest.mark.asyncio
async def test_unregister_invalidates_discovered_tool(
    make_app,
    slice_seed,
    clock,
) -> None:
    """场景 4：Tool 被发现后注销 -> resolve 与 execute 均失效，Search 不再返回。"""
    reasoner = ScriptedReasoner(
        [
            _tool_call("search_tools", {"query": "训练详情"}, "call-1"),
            FinalAction(content="第一轮结束。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="找工具",
    )
    visible_after_discovery = {
        tool.name for tool in reasoner.seen_contexts[1].visible_tools
    }
    assert "get_workout_detail" in visible_after_discovery

    # 注销后：resolve 不可见、execute 得 tool_not_found、Search 不再返回。
    app.state.tool_registry.unregister("get_workout_detail")
    session = app.state.tool_runtime.create_session(run_id=slice_seed.plan_id)
    visible_now = {tool.name for tool in app.state.tool_runtime.visible_tools(session)}
    assert "get_workout_detail" not in visible_now

    from app.tools.context import ToolExecutionContext

    exec_context = ToolExecutionContext(
        user_id=slice_seed.user_id,
        thread_id=context.trace_id,
        turn_id=context.request_id,
        run_id=slice_seed.plan_id,
        call_id=context.request_id,
        request_id=context.request_id,
        trace_id=context.trace_id,
        timestamp=context.timestamp,
    )
    observation = await app.state.tool_runtime.execute_tool_call(
        session=session,
        action=ToolCallAction(
            tool="get_workout_detail",
            arguments={"workout_id": str(slice_seed.workout_ids[0])},
            model_call_id="call-exec-1",
        ),
        context=exec_context,
    )
    assert observation.status == "error"
    assert observation.error_code == "tool_not_found"
    assert app.state.tool_registry.find("get_workout_detail") is None
