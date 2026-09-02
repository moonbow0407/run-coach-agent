"""Settings 启动期校验：JWT 密钥长度等配置不变量。"""

import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings


def test_jwt_secret_must_have_at_least_32_characters() -> None:
    """验证：JWT 密钥不足 32 字符时构造 Settings 直接失败（fail fast）。"""
    # pytest.raises：断言代码块抛出预期异常，否则测试失败
    with pytest.raises(ValidationError):
        Settings(jwt_secret="too-short")
