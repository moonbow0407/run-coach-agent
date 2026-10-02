"""Turn 生命周期事件契约：TurnCommitted 只在提交成功后发布，失败/提交崩溃/监听器异常各有边界。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.lifecycle.events import TurnCommitted, TurnFailed, TurnStarted
from app.agent.models.action import FinalAction
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.scripted import FailingReasoner, ScriptedReasoner
from app.common.clock import FrozenClock
from app.common.errors import InfrastructureError
from tests.helpers import event_types, load_turn, load_turn_messages, record_events


@pytest.mark.asyncio
async def test_turn_committed_is_published_only_after_commit(
    make_app,
    user_id,
    auth_header,
    sessions,
    clock: FrozenClock,
) -> None:
    """验证：TurnCommitStarted 先于 TurnCommitted 发布，事件与落库的 Turn 状态、助手消息一致。"""
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
    # 顺序约束：必须先"开始提交"，提交成功后才有"已提交"事件。
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
    """验证：推理失败的 Turn 只发 TurnFailed，绝不出现 TurnCommitted；用户消息保留、无助手消息。"""
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


@pytest.mark.asyncio
async def test_commit_failure_marks_turn_failed(
    make_app,
    auth_header,
    sessions,
    monkeypatch,
) -> None:
    """验证：提交阶段抛错时 Turn 落为 FAILED 且不发 TurnCommitted——终态事件与事务结果绑定。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="不会提交")]))
    events = record_events(app.state.lifecycle)

    async def fail_commit(**_kwargs):
        raise InfrastructureError("提交失败")

    # monkeypatch：临时把 commit_turn 换成必抛错版本，模拟提交崩溃。
    monkeypatch.setattr(app.state.conversation_store, "commit_turn", fail_commit)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "触发提交失败"},
            headers=auth_header,
        )

    assert response.status_code == 500
    assert "TurnCommitted" not in event_types(events)
    failed = next(event for event in events if isinstance(event, TurnFailed))
    turn = await load_turn(sessions, failed.turn_id)
    assert turn.status == TurnStatus.FAILED.value
    assert turn.assistant_message_id is None


@pytest.mark.asyncio
async def test_turn_committed_listener_failure_does_not_change_success(
    make_app,
    auth_header,
    sessions,
) -> None:
    """验证：TurnCommitted 之后监听器崩溃不影响已成功的响应与落库——提交后阶段不是失败回滚区。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="已经提交")]))
    events = record_events(app.state.lifecycle)

    # 恶意监听器：只在收到 TurnCommitted 时抛错，模拟提交后投影方故障。
    def broken_projector(event) -> None:
        if isinstance(event, TurnCommitted):
            raise OSError("projector unavailable")

    app.state.lifecycle.subscribe(broken_projector)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "提交后投影失败"},
            headers=auth_header,
        )

    assert response.status_code == 200
    assert response.json()["content"] == "已经提交"
    committed = next(event for event in events if isinstance(event, TurnCommitted))
    turn = await load_turn(sessions, committed.turn_id)
    assert turn.status == TurnStatus.COMMITTED.value
