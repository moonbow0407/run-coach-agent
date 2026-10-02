"""在供应商边界保留可重试性，不向上层暴露响应正文或密钥。"""

from openai import APIConnectionError, APIError, APIStatusError

from app.common.errors import InfrastructureError


def normalize_openai_error(exc: APIError, *, code: str) -> InfrastructureError:
    """仅连接/超时、408、409、429 和服务端故障可重试，其余永久失败。"""
    retryable = isinstance(exc, APIConnectionError) or (
        isinstance(exc, APIStatusError)
        and (exc.status_code in {408, 409, 429} or 500 <= exc.status_code < 600)
    )
    return InfrastructureError(code, retryable=retryable)
