import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction
from app.agent.reasoning.scripted import ScriptedReasoner


@pytest.mark.asyncio
async def test_current_plan_question_uses_working_context(
    make_app,
    slice_seed,
    slice_auth_header,
) -> None:
    # 不按关键词路由；Reasoner 自行决定直接给出 Final。
    reasoner = ScriptedReasoner([FinalAction(content="当前计划覆盖第 6 周。")])
    app = make_app(reasoner=reasoner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "下周我要比赛，现在计划是什么？"},
            headers=slice_auth_header,
        )
    assert response.status_code == 200
    assert response.json()["content"] == "当前计划覆盖第 6 周。"
    bundle = reasoner.seen_contexts[0].context_bundle
    assert bundle.working_context.active_plan is not None
    assert bundle.working_context.active_plan.version == 1
    assert len(bundle.working_context.active_plan.sessions) == 2
    assert reasoner.seen_contexts[0].state.interactions == []
