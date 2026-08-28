import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner


@pytest.mark.asyncio
async def test_goal_tool_discovered_then_called(
    make_app,
    slice_seed,
    slice_auth_header,
) -> None:
    """Phase 2 语义：get_active_goal 是隐藏 Tool，
    经 search_tools 发现后同 Run 内可成功执行。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="search_tools",
                arguments={"query": "训练目标 比赛"},
                model_call_id="call-search-1",
            ),
            ToolCallAction(
                tool="get_active_goal",
                arguments={},
                model_call_id="call-goal-1",
            ),
            FinalAction(content="目标是 10 月半马 1:50。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "我的比赛目标是什么？"},
            headers=slice_auth_header,
        )
    assert response.status_code == 200

    # 发现后下一轮可见集合包含 get_active_goal。
    visible = {tool.name for tool in reasoner.seen_contexts[1].visible_tools}
    assert "get_active_goal" in visible

    observation = reasoner.seen_contexts[2].state.interactions[3]
    assert observation.status == "success"
    assert observation.data["target_time_s"] == 6600
    assert observation.data["race_distance_m"] == 21097
