import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.lifecycle.events import TurnCommitted, TurnFailed
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.scripted import FailingReasoner
from tests.helpers import load_turn, load_turn_messages, record_events


@pytest.mark.asyncio
async def test_failed_turn(
    make_app,
    slice_seed,
    slice_auth_header,
    sessions,
) -> None:
    app = make_app(reasoner=FailingReasoner())
    events = record_events(app.state.lifecycle)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "请分析我的状态"},
            headers=slice_auth_header,
        )
        assert response.status_code == 500
        listed = await client.get(
            f"/api/v1/threads/{_thread_id_from_failed(events)}/messages",
            headers=slice_auth_header,
        )

    assert not any(isinstance(event, TurnCommitted) for event in events)
    failed = next(event for event in events if isinstance(event, TurnFailed))
    turn = await load_turn(sessions, failed.turn_id)
    assert turn.status == TurnStatus.FAILED.value
    assert turn.assistant_message_id is None
    messages = await load_turn_messages(sessions, failed.turn_id)
    assert [message.role for message in messages] == ["user"]
    assert listed.status_code == 200
    assert listed.json()["messages"] == []


def _thread_id_from_failed(events) -> str:
    failed = next(event for event in events if isinstance(event, TurnFailed))
    return str(failed.thread_id)
