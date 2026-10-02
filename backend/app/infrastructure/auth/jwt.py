"""JWT 签发与校验：认证的基础设施实现。

业务层只见 AuthenticationError，不感知 PyJWT 的异常类型。
"""

from datetime import datetime
from uuid import UUID

import jwt

from app.common.errors import AuthenticationError


def issue_token(
    *,
    user_id: UUID,
    secret: str,
    now: datetime,
    expire_seconds: int,
    algorithm: str = "HS256",
) -> str:
    """为指定用户签发 JWT；sub 字段即 user_id。仅供本地脚本 / 测试使用。"""
    payload = {
        "sub": str(user_id),  # JWT 标准声明：主体，这里即用户 ID
        "iat": int(now.timestamp()),  # 签发时间（Unix 秒）
        "exp": int(now.timestamp()) + expire_seconds,  # 过期时间（Unix 秒）
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_user_id(*, token: str, secret: str, algorithm: str = "HS256") -> UUID:
    """校验令牌并取出 user_id；过期 / 无效 / 缺字段统一转为 AuthenticationError。"""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("令牌已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("令牌无效") from exc

    sub = payload.get("sub")
    if not sub:
        raise AuthenticationError("令牌缺少 sub")
    try:
        return UUID(str(sub))
    except ValueError as exc:
        raise AuthenticationError("令牌 sub 不是合法用户 ID") from exc
