import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.lifecycle.events import TurnCommitted, TurnFailed, TurnStarted
from app.agent.models.action import FinalAction
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.scripted import FailingReasoner, ScriptedReasoner
from app.common.clock import FrozenClock
from app.common.errors import ReasonerError
from tests.helpers import event_types, load_turn, load_turn_messages, record_events


@pytest.mark.asyncio
async def test_turn_committed_is_published_only_after_commit(
    make_app,
    user_id,
    auth_header,
    sessions,
    clock: FrozenClock,
) -> None:
    reasoner = ScriptedReasoner([FinalAction(content="好的。")])
    app = make_app(reasoner=reasoner)
    events = record_events(app.state.lifecycle)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "你好"},
            headers=auth_header,
        )
    assert response.status_code == 200
    body = response.json()
    types = event_types(events)
    assert types[0] == "TurnStarted"
    assert types[-1] == "TurnCommitted"
    commit_index = types.index("TurnCommitStarted")
    committed_index = types.index("TurnCommitted")
    assert commit_index < committed_index

    turn = await load_turn(sessions, body["turn_id"])
    assert turn.status == TurnStatus.COMMITTED.value
    started = next(event for event in events if isinstance(event, TurnStarted))
    committed = next(event for event in events if isinstance(event, TurnCommitted))
    assert started.turn_id == committed.turn_id
    assert committed.assistant_message_id == turn.assistant_message_id


@pytest.mark.asyncio
async def test_failed_turn_never_publishes_turn_committed(
    make_app,
    user_id,
    auth_header,
    sessions,
) -> None:
    app = make_app(reasoner=FailingReasoner())
    events = record_events(app.state.lifecycle)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "会失败"},
            headers=auth_header,
        )
    assert response.status_code == 500
    assert "TurnCommitted" not in event_types(events)
    assert any(isinstance(event, TurnFailed) for event in events)
    failed = next(event for event in events if isinstance(event, TurnFailed))
    turn = await load_turn(sessions, failed.turn_id)
    assert turn.status == TurnStatus.FAILED.value
    assert turn.assistant_message_id is None
    messages = await load_turn_messages(sessions, failed.turn_id)
    assert [message.role for message in messages] == ["user"]
    assert messages[0].content == "会失败"
