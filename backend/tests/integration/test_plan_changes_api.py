"""计划确认 HTTP 边界：JWT user_id、响应 body、幂等 confirm。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.common.ids import new_id
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from tests.conftest import token_for
from tests.helpers import request_context_for


@pytest.mark.asyncio
async def test_plan_change_http_get_confirm_reject_bodies(
    make_app,
    slice_seed,
    clock,
    sessions,
    slice_auth_header,
    test_settings,
) -> None:
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="search_tools",
                arguments={"query": "降负荷 调整草案", "limit": 5},
                model_call_id="c1",
            ),
            ToolCallAction(
                tool="propose_plan_adaptation",
                arguments={
                    "based_on_plan_version": 1,
                    "based_on_state_version": 2,
                    "horizon_days": 7,
                    "reason": "高疲劳降低节奏课",
                },
                model_call_id="c2",
            ),
            FinalAction(content="草案已提出。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    await app.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now()
    )
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="请降低接下来的负荷",
    )
    from sqlalchemy import select

    from app.infrastructure.database.models.coaching import PlanChangeRow

    async with short_session(sessions) as session:
        change_id = await session.scalar(
            select(PlanChangeRow.id).where(PlanChangeRow.user_id == slice_seed.user_id)
        )
    assert change_id is not None
    other_id = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other_id, created_at=clock.now(), updated_at=clock.now()))
    other_header = {"Authorization": f"Bearer {token_for(other_id, test_settings)}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get(
            f"/api/v1/plan-changes/{change_id}", headers=other_header
        )
        assert missing.status_code == 404
        fetched = await client.get(
            f"/api/v1/plan-changes/{change_id}", headers=slice_auth_header
        )
        assert fetched.status_code == 200
        payload = fetched.json()
        assert payload["id"] == str(change_id)
        assert payload["status"] == "pending_confirmation"
        assert payload["change_type"] == "reduce_upcoming_load"
        first = await client.post(
            f"/api/v1/plan-changes/{change_id}/confirm", headers=slice_auth_header
        )
        assert first.status_code == 200
        body = first.json()
        assert body["plan_change"]["status"] == "confirmed"
        assert body["resulting_plan_id"] == body["resulting_plan"]["id"]
        by_date = {item["scheduled_date"]: item for item in body["resulting_plan"]["sessions"]}
        assert by_date["2026-08-29"]["session_type"] == "easy"
        assert by_date["2026-08-31"]["session_type"] == "rest"
        assert by_date["2026-08-31"]["prescription"] == {}
        second = await client.post(
            f"/api/v1/plan-changes/{change_id}/confirm", headers=slice_auth_header
        )
        assert second.status_code == 200
        assert second.json()["resulting_plan_id"] == body["resulting_plan_id"]
        rejected = await client.post(
            f"/api/v1/plan-changes/{change_id}/reject", headers=slice_auth_header
        )
        assert rejected.status_code == 409
