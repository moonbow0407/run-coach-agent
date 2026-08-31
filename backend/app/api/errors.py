"""领域错误族 → HTTP 状态码的唯一映射点。

api 传输层的错误归一化：所有路由把 RunCoachError 交给这里翻译，
保证同一领域错误在任意路由上的语义（状态码）一致，
且不会向客户端泄漏内部堆栈等基础设施细节（ARCHITECTURE §45）。
"""

from fastapi import HTTPException, status

from app.common.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RunCoachError,
)


def to_http_error(exc: RunCoachError) -> HTTPException:
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, DomainError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
