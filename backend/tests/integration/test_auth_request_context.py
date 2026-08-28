from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.infrastructure.config import Settings
from tests.conftest import token_for


@pytest.mark.asyncio
async def test_missing_token_is_unauthorized(make_app) -> None:
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "hi"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_is_unauthorized(make_app) -> None:
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
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "hi", "user_id": str(uuid4())},
            headers=auth_header,
        )
    assert response.status_code == 422
