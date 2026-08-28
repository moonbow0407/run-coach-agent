import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.common.clock import FrozenClock
from app.common.errors import RunCoachError
from app.common.ids import new_id
from app.infrastructure.config import Settings
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from tests.conftest import token_for


@pytest.mark.asyncio
async def test_health(make_app) -> None:
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_and_list_committed_messages(
    make_app,
    auth_header,
) -> None:
    reasoner = ScriptedReasoner([FinalAction(content="收到，我们从目标开始。")])
    app = make_app(reasoner=reasoner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/chat",
            json={"message": "你好，教练"},
            headers=auth_header,
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["content"] == "收到，我们从目标开始。"
        assert payload["thread_id"]
        assert payload["turn_id"]
        assert payload["message_id"]
        thread_id = payload["thread_id"]

        listed = await client.get(
            f"/api/v1/threads/{thread_id}/messages",
            headers=auth_header,
        )
    assert listed.status_code == 200
    messages = listed.json()["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "你好，教练"
    assert messages[1]["content"] == "收到，我们从目标开始。"


@pytest.mark.asyncio
async def test_other_user_cannot_read_thread(
    make_app,
    auth_header,
    sessions,
    test_settings: Settings,
    clock: FrozenClock,
) -> None:
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="ok")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/chat",
            json={"message": "私有对话"},
            headers=auth_header,
        )
        thread_id = created.json()["thread_id"]

        other_id = new_id()
        async with short_session(sessions, commit=True) as session:
            session.add(UserRow(id=other_id, created_at=clock.now(), updated_at=clock.now()))
        other_token = token_for(other_id, test_settings)
        listed = await client.get(
            f"/api/v1/threads/{thread_id}/messages",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        missing = await client.get(
            f"/api/v1/threads/{uuid4()}/messages",
            headers=auth_header,
        )
    assert listed.status_code == 404
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_chat_sse_emits_lifecycle_events(
    make_app,
    auth_header,
) -> None:
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="流式完成")]))
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"message": "hello"},
            headers=auth_header,
        ) as response,
    ):
        assert response.status_code == 200
        body = (await response.aread()).decode()
    assert "event: run.started" in body
    assert "event: reasoning.started" in body
    assert "event: response.delta" in body
    assert "流式完成" in body
    assert "event: run.completed" in body


@pytest.mark.asyncio
async def test_chat_sse_finishes_when_task_fails_without_terminal_event(
    make_app,
    auth_header,
    monkeypatch,
) -> None:
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="unused")]))

    async def fail_without_event(**_kwargs):
        raise RunCoachError("early failure")

    monkeypatch.setattr(app.state.chat_service, "send_message", fail_without_event)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with asyncio.timeout(2):
            async with client.stream(
                "POST",
                "/api/v1/chat/stream",
                json={"message": "hello"},
                headers=auth_header,
            ) as response:
                body = (await response.aread()).decode()

    assert response.status_code == 200
    assert "event: run.failed" in body
    assert "请求执行失败" in body
