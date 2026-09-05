"""GET /api/v1/safety/status 包装 SafetyGate.status_for。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.tools.safety.constants import FLAG_HIGH_FATIGUE_POOR_RECOVERY
from app.tools.safety.gate import SafetyGate
from app.tools.safety.policy import SafetyStatus


class _StubGate(SafetyGate):
    """绕过取证，直接返回固定安全状态。"""

    def __init__(self, status: SafetyStatus) -> None:
        # 不调用父类 __init__：测试不需要真实 evidence。
        self._status = status

    async def status_for(self, *, user_id):
        return self._status


@pytest.mark.asyncio
async def test_safety_status_ok(make_app, auth_header) -> None:
    """验证：无约束时返回 ok=true。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    app.state.safety_gate = _StubGate(SafetyStatus(ok=True, flags=(), reasons=()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/safety/status", headers=auth_header)
    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "flags": [], "reasons": []}


@pytest.mark.asyncio
async def test_safety_status_with_flags(make_app, auth_header) -> None:
    """验证：疲劳 flag 与中文 reasons 原样返回。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    app.state.safety_gate = _StubGate(
        SafetyStatus(
            ok=False,
            flags=(FLAG_HIGH_FATIGUE_POOR_RECOVERY,),
            reasons=("最新状态为高疲劳且恢复差：仅允许降负荷/转轻松跑草案与只读工具",),
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/safety/status", headers=auth_header)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert FLAG_HIGH_FATIGUE_POOR_RECOVERY in body["flags"]
    assert body["reasons"]


@pytest.mark.asyncio
async def test_safety_status_requires_auth(make_app) -> None:
    """验证：未带令牌时 401。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/safety/status")
    assert response.status_code == 401
