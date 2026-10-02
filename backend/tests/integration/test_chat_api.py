"""聊天 HTTP 边界：对话消息入库、会话线程归属隔离、SSE 流式生命周期与失败兜底。"""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction
from app.agent.reasoning.llm_reasoner import LLMReasoner
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.agent.reasoning.scripted import ScriptedReasoner
from app.common.clock import FrozenClock
from app.common.errors import RunCoachError
from app.common.ids import new_id
from app.infrastructure.config import Settings
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from app.infrastructure.llm.provider import OpenAICompatibleProvider
from tests.conftest import token_for
from tests.helpers import load_turn_messages


def _parse_sse_frames(body: str) -> list[tuple[str, dict]]:
    """把 SSE 字节流解析成（事件名, 载荷）帧序列，分帧规则与前端 sse.ts 一致。"""
    frames: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event_name: str | None = None
        payload: dict = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                payload = json.loads(line[len("data: "):])
        if event_name is not None:
            frames.append((event_name, payload))
    return frames


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
    sessions,
) -> None:
    """验证：SSE 按序输出生命周期事件；正文增量逐帧先于 run.completed，且拼接等于落库助手正文。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="流式完成")]))
    # client.stream + aread：读取 SSE（Server-Sent Events）完整字节流后按帧断言。
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

    frames = _parse_sse_frames(body)
    names = [name for name, _ in frames]
    assert names[0] == "run.started"
    assert "reasoning.started" in names
    assert names[-1] == "run.completed"

    # 正文增量帧必须全部先于 run.completed（终态之后前端不再接受增量）。
    delta_frames = [payload for name, payload in frames if name == "response.delta"]
    assert delta_frames, "流式接口必须产生正文增量帧"
    completed_index = names.index("run.completed")
    assert all(
        index < completed_index
        for index, name in enumerate(names)
        if name == "response.delta"
    )
    # 增量来自最终回答步骤：step_index 与循环下标一致。
    assert all(payload["step_index"] == 0 for payload in delta_frames)
    # 关键契约：最后一个 step 的增量拼接 == commit_turn 落库的助手正文。
    delta_text = "".join(payload["content"] for payload in delta_frames)
    assert delta_text == "流式完成"
    turn_id = UUID(frames[-1][1]["turn_id"])
    messages = await load_turn_messages(sessions, turn_id)
    assistant = [message for message in messages if message.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == delta_text


class _FakeStreamChunk:
    """流式 chunk 替身：只携带 content 增量，字段名对齐 OpenAI 协议。"""

    def __init__(self, content: str) -> None:
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content, "tool_calls": None})()})()]
        self.model = "fake-stream-model"


class _FakeStream:
    """异步流替身：支持 async with / async for，逐个回放文本片段。"""

    def __init__(self, fragments: list[str]) -> None:
        self._fragments = list(fragments)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._fragments:
            raise StopAsyncIteration
        return _FakeStreamChunk(self._fragments.pop(0))


class _FakeStreamClient:
    """OpenAI client 流式替身：chat.completions.create 必须以 stream=True 调用。"""

    def __init__(self, fragments: list[str]) -> None:
        self._stream = _FakeStream(fragments)
        self.chat = type("Chat", (), {"completions": self})()

    async def create(self, **kwargs):
        assert kwargs.get("stream") is True, "生产路径应始终走流式请求"
        return self._stream


@pytest.mark.asyncio
async def test_chat_sse_streams_real_provider_token_deltas(
    make_app,
    auth_header,
    sessions,
) -> None:
    """端到端流式切片：真 Provider 聚合 + LLMReasoner + /chat/stream，多帧小增量且拼接等于落库正文。"""
    provider = OpenAICompatibleProvider(
        client=_FakeStreamClient(["正在", "流式", "回复"]),  # type: ignore[arg-type]
        model="fake-stream-model",
    )
    app = make_app(reasoner=LLMReasoner(provider, PromptRenderer()))
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"message": "hello"},
            headers=auth_header,
        ) as response,
    ):
        body = (await response.aread()).decode()

    frames = _parse_sse_frames(body)
    delta_frames = [payload for name, payload in frames if name == "response.delta"]
    # 每个 chunk 一帧：前端视角是逐段打字机，而非一次性全文。
    assert [payload["content"] for payload in delta_frames] == ["正在", "流式", "回复"]
    delta_text = "".join(payload["content"] for payload in delta_frames)
    turn_id = UUID(frames[-1][1]["turn_id"])
    messages = await load_turn_messages(sessions, turn_id)
    assistant = [message for message in messages if message.role == "assistant"]
    assert assistant[0].content == delta_text == "正在流式回复"


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
