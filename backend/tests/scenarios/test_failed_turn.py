"""端到端教练场景测试：推理失败的 Turn。

推理器抛错时 API 返回 500，Turn 落库为 FAILED 且无助手回复，
对外线程消息列表保持为空、不泄露半成品内容。
"""

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
    """场景：推理器直接抛错 → 期望：HTTP 500，Turn 记为 FAILED，线程消息接口只返回空列表。"""
    # FailingReasoner：脚本化假推理器，一被调用就抛错，模拟模型推理失败。
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

    # 失败的 Turn 不允许提交。
    assert not any(isinstance(event, TurnCommitted) for event in events)
    failed = next(event for event in events if isinstance(event, TurnFailed))
    turn = await load_turn(sessions, failed.turn_id)
    assert turn.status == TurnStatus.FAILED.value
    assert turn.assistant_message_id is None
    messages = await load_turn_messages(sessions, failed.turn_id)
    assert [message.role for message in messages] == ["user"]
    # 对外线程视角：失败 Turn 不产生任何可见消息。
    assert listed.status_code == 200
    assert listed.json()["messages"] == []


def _thread_id_from_failed(events) -> str:
    """从 TurnFailed 生命周期事件中取回失败 Turn 所属的会话线程 ID。"""
    failed = next(event for event in events if isinstance(event, TurnFailed))
    return str(failed.thread_id)
