"""端到端教练场景测试：用户询问最近训练状态。

走 HTTP 接口完整链路：模型调用近期训练 Tool 后给出总结回复，
验证 Turn 正常提交、RunStep 轨迹落库与 WorkingContext 注入。
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.lifecycle.events import TurnCommitted
from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.scripted import ScriptedReasoner
from tests.helpers import event_types, load_run_steps, load_turn, record_events


@pytest.mark.asyncio
async def test_recent_training_analysis(
    make_app,
    slice_seed,
    slice_auth_header,
    sessions,
) -> None:
    """场景：用户问「最近训练状态怎么样」→ 期望：先调 get_recent_workouts 再 Final 作答，Turn 正常提交且轨迹可回放。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="get_recent_workouts",
                arguments={"days": 14},
                model_call_id="call-recent-1",
            ),
            FinalAction(content="最近有一次间歇和一次长跑，疲劳为中等。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    # record_events：订阅生命周期事件到内存列表，供断言检查 Turn 状态流转。
    events = record_events(app.state.lifecycle)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "我最近训练状态怎么样？"},
            headers=slice_auth_header,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "最近有一次间歇和一次长跑，疲劳为中等。"
    # 成功对话必须以 TurnCommitted 事件收尾。
    assert "TurnCommitted" in event_types(events)
    assert any(isinstance(event, TurnCommitted) for event in events)

    turn = await load_turn(sessions, body["turn_id"])
    assert turn.status == TurnStatus.COMMITTED.value

    committed = next(event for event in events if isinstance(event, TurnCommitted))
    steps = await load_run_steps(sessions, committed.run_id)
    kinds = [step.kind for step in steps]
    assert "tool_call" in kinds
    assert "observation" in kinds
    assert "final" in kinds
    call = next(step for step in steps if step.kind == "tool_call")
    observation = next(step for step in steps if step.kind == "observation")
    assert call.call_id == observation.call_id
    assert call.input_data is not None
    assert call.input_data["tool"] == "get_recent_workouts"
    assert observation.output_data is not None
    assert observation.output_data["status"] == "success"
    # seed 共播种四次训练（轻松/节奏/长距离/间歇）。
    assert len(observation.output_data["data"]["workouts"]) == 4

    # 推理器首轮上下文：用户原话 + 目标与状态快照均已注入。
    bundle = reasoner.seen_contexts[0].context_bundle
    assert bundle.current_input == "我最近训练状态怎么样？"
    assert bundle.working_context.goal is not None
    assert bundle.working_context.goal.target_time_s == 6600
    assert bundle.working_context.latest_athlete_state is not None
    # seed 快照 v1：中等疲劳。
    assert bundle.working_context.latest_athlete_state.fatigue_level == "moderate"
