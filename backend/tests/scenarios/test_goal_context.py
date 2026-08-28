import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.reasoning.scripted import ScriptedReasoner


@pytest.mark.asyncio
async def test_goal_is_in_working_context(
    make_app,
    slice_seed,
    slice_auth_header,
) -> None:
    reasoner = ScriptedReasoner(
        [
            CapabilityCallAction(capability="get_active_goal", arguments={}),
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
    bundle = reasoner.seen_contexts[0].context_bundle
    goal = bundle.working_context.goal
    assert goal is not None
    assert goal.race_distance_m == 21097
    assert goal.target_time_s == 6600
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "success"
    assert observation.data["target_time_s"] == 6600
