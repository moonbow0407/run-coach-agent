"""聊天 HTTP 边界：对话消息入库、会话线程归属隔离、SSE 流式生命周期与失败兜底。"""

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
    """验证：健康检查端点返回 200 与固定状态体。"""
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
    """验证：发送消息完成一轮对话后，用户与助手消息按序提交，可按会话线程回查。"""
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
    """验证：其他用户读取他人会话线程返回 404（不暴露存在性），不存在的线程同样 404。"""
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
    """验证：SSE 流式接口按序输出 run.started→reasoning→response.delta→run.completed 事件及最终回复。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="流式完成")]))
    # client.stream + aread：读取 SSE（Server-Sent Events）完整字节流后断言事件文本。
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
    """验证：任务在发布终态事件前就抛错时，SSE 仍能收尾并输出 run.failed，连接不挂死。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="unused")]))

    async def fail_without_event(**_kwargs):
        raise RunCoachError("early failure")

    # monkeypatch：临时把 send_message 换成直接抛错的版本，模拟"未发事件先崩溃"。
    monkeypatch.setattr(app.state.chat_service, "send_message", fail_without_event)
    # asyncio.timeout：限时守卫，若 SSE 流不结束则测试超时失败。
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
