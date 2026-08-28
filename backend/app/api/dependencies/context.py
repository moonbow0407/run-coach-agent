from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select

from app.common.errors import AuthenticationError
from app.common.ids import new_id
from app.identity.application.request_context import RequestContext
from app.infrastructure.auth.jwt import decode_user_id
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session


async def get_request_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_request_id: Annotated[str | None, Header()] = None,
    x_trace_id: Annotated[str | None, Header()] = None,
) -> RequestContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证令牌")
    token = authorization.split(" ", 1)[1].strip()
    settings = request.app.state.settings
    clock = request.app.state.clock
    try:
        user_id = decode_user_id(
            token=token,
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    async with short_session(request.app.state.sessions) as session:
        exists = await session.scalar(select(UserRow.id).where(UserRow.id == user_id))
        if exists is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    return RequestContext(
        user_id=user_id,
        request_id=_header_uuid(x_request_id) or new_id(),
        trace_id=_header_uuid(x_trace_id) or new_id(),
        timestamp=clock.now(),
    )


def _header_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
