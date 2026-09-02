"""请求鉴权依赖：在系统入口解析一次用户身份，形成可信 RequestContext。

这是身份边界（ARCHITECTURE §31）的实现：

    user_id 只能来自 JWT 认证，绝不从请求体、模型输出或能力参数读取。
    解析结果沿执行链向下传播，所有数据访问都以它做用户数据隔离。
"""

from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException, Request, status
from sqlalchemy import select

from app.common.errors import AuthenticationError
from app.common.ids import new_id
from app.identity.application.request_context import RequestContext
from app.infrastructure.auth.jwt import decode_user_id
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session


async def get_request_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,  # Bearer JWT 令牌
    x_request_id: Annotated[str | None, Header()] = None,  # 网关传入的请求 ID（可选）
    x_trace_id: Annotated[str | None, Header()] = None,  # 跨服务链路追踪 ID（可选）
) -> RequestContext:
    """Bearer Token → user_id → RequestContext。

    request_id / trace_id 优先取请求头（便于跨服务串联），否则现场生成。
    """
    # 缺少 Bearer 头：请求未认证。
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
        # 令牌签名 / 格式不合法：按 401 处理。
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # 令牌合法不代表账号仍存在：再查一次用户表，防止已删除用户持旧令牌访问。
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
    """把请求头解析为 UUID；非法值视为未提供（调用方会现场生成新 ID）。"""
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
