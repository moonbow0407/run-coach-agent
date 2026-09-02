"""Agent 运行时主循环链路：send_message 驱动 reason→tool→observe→final，事件与 RunStep 全程落库。"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.observation import Observation
from app.agent.reasoning.scripted import ScriptedReasoner
from app.common.clock import FrozenClock
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.vertical_slice import seed_vertical_slice
from tests.helpers import event_types, load_run_steps, record_events, request_context_for


@pytest.mark.asyncio
async def test_runtime_reason_act_observe_final_and_call_id_pairing(
    make_app,
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """验证：一轮完整对话中 RunStep 按五段顺序落库，ToolCall 与 Observation 通过同一 call_id 配对，事件流完整无失败。"""
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)

    # ScriptedReasoner：按预设动作序列回放的桩推理器，代替真实 LLM，使输出可断言。
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="get_recent_workouts",
                arguments={"days": 14},
                model_call_id="call-recent-1",
            ),
            FinalAction(content="最近四次训练都完成了。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    # record_events：订阅生命周期事件总线，把事件按发布顺序收进列表供断言。
    events = record_events(app.state.lifecycle)
    context = request_context_for(seed.user_id, clock)
    result = await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="我最近训练状态怎么样？",
    )

    assert result.content == "最近四次训练都完成了。"
    types = event_types(events)
    # 事件顺序即 Turn 状态机：开始→（组装/工具中段）→提交收尾，且全程不允许出现 TurnFailed。
    assert types[0] == "TurnStarted"
    assert "ContextAssembled" in types
    assert "ToolStarted" in types
    assert "ToolCompleted" in types
    assert types[-1] == "TurnCommitted"
    assert "TurnFailed" not in types
    # 全链路 trace_id 贯穿：所有事件都属于这一次请求。
    assert all(event.trace_id == context.trace_id for event in events)

    steps = await load_run_steps(sessions, result.run_id)
    kinds = [step.kind for step in steps]
    # 第二段 reasoning 应看到工具结果，说明循环真的走了两轮推理。
    assert kinds == ["reasoning", "tool_call", "observation", "reasoning", "final"]
    call = next(step for step in steps if step.kind == "tool_call")
    observation = next(step for step in steps if step.kind == "observation")
    assert call.call_id is not None
    # 调用与观测共享同一 call_id，是对应关系可追溯的协议约束。
    assert call.call_id == observation.call_id
    assert call.input_data is not None
    assert call.input_data["tool"] == "get_recent_workouts"
    # RunStep 保存 model_call_id，Observation 携带同一协议 ID。
    assert call.input_data["model_call_id"] == "call-recent-1"
    assert observation.output_data is not None
    assert observation.output_data["model_call_id"] == "call-recent-1"

    # 第二轮推理的 state.interactions 应包含上一轮的 ToolCall 与 Observation，验证短期记忆回填。
    first_state = reasoner.seen_contexts[0].state
    second_state = reasoner.seen_contexts[1].state
    assert first_state.interactions == []
    assert len(second_state.interactions) == 2
    assert isinstance(second_state.interactions[0], ToolCallAction)
    assert isinstance(second_state.interactions[1], Observation)
    assert second_state.interactions[1].status == "success"
    assert isinstance(second_state.interactions[1].data, dict)
    assert len(second_state.interactions[1].data["workouts"]) == 4

    # 初始可见 Tool 恰为 always-on 两个：search_tools + get_recent_workouts。
    visible_names = {tool.name for tool in reasoner.seen_contexts[0].visible_tools}
    assert visible_names == {"search_tools", "get_recent_workouts"}
