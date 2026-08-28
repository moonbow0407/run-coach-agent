
import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.lifecycle.events import TurnCommitted
from app.agent.models.action import FinalAction
from app.agent.reasoning.scripted import FailingReasoner, ScriptedReasoner
from app.common.clock import FrozenClock
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.vertical_slice import seed_vertical_slice
from tests.conftest import token_for
from tests.helpers import event_types, record_events


@pytest.mark.asyncio
async def test_current_input_is_excluded_from_recent_messages(
    make_app,
    sessions,
    test_settings,
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    reasoner = ScriptedReasoner([FinalAction(content="了解，当前目标是半马。")])
    app = make_app(reasoner=reasoner)
    token = token_for(seed.user_id, test_settings, clock)
    current = "我最近训练状态怎么样？"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": current},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert reasoner.seen_contexts
    bundle = reasoner.seen_contexts[0].context_bundle
    assert bundle.current_input == current
    assert all(message.content != current for message in bundle.recent_messages)
    assert bundle.working_context.goal is not None
    assert bundle.working_context.active_plan is not None
    assert bundle.working_context.latest_athlete_state is not None
    assert bundle.semantic_memories == []
    assert bundle.episodic_memories == []


@pytest.mark.asyncio
async def test_failed_turn_user_message_is_not_in_later_context(
    make_app,
    sessions,
    test_settings,
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    token = token_for(seed.user_id, test_settings, clock)
    failed_text = "这次会失败的问题"
    success_text = "再问一次计划"

    fail_app = make_app(reasoner=FailingReasoner())
    async with AsyncClient(transport=ASGITransport(app=fail_app), base_url="http://test") as client:
        failed = await client.post(
            "/api/v1/chat",
            json={"message": failed_text},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert failed.status_code == 500

    reasoner = ScriptedReasoner([FinalAction(content="当前是第 6 周计划。")])
    ok_app = make_app(reasoner=reasoner)
    events = record_events(ok_app.state.lifecycle)
    async with AsyncClient(transport=ASGITransport(app=ok_app), base_url="http://test") as client:
        ok = await client.post(
            "/api/v1/chat",
            json={"message": success_text},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert ok.status_code == 200
    assert "TurnCommitted" in event_types(events)
    bundle = reasoner.seen_contexts[0].context_bundle
    contents = [message.content for message in bundle.recent_messages]
    assert failed_text not in contents
    assert bundle.current_input == success_text
    assert any(isinstance(event, TurnCommitted) for event in events)
