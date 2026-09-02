"""认证边界：请求身份只能来自 JWT 中的 user_id，缺失/伪造/未知用户一律拒绝。"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.infrastructure.config import Settings
from tests.conftest import token_for


@pytest.mark.asyncio
async def test_missing_token_is_unauthorized(make_app) -> None:
    """验证：请求不带 Authorization 头返回 401，接口不允许匿名访问。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    # AsyncClient + ASGITransport：httpx 直接驱动 FastAPI 应用，不经过真实网络。
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "hi"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_is_unauthorized(make_app) -> None:
    """验证：签名非法的 JWT 返回 401，伪造身份无法通过校验。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": "Bearer not-a-token"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_for_unknown_user_is_unauthorized(
    make_app,
    test_settings: Settings,
) -> None:
    """验证：JWT 签名合法但用户不存在于库中时仍拒绝，不盲信 token 内容。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    token = token_for(uuid4(), test_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_id_in_body_is_rejected(make_app, auth_header) -> None:
    """验证：请求体试图自带 user_id 覆盖身份返回 422，身份字段只允许来自 token。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "hi", "user_id": str(uuid4())},
            headers=auth_header,
        )
    assert response.status_code == 422
