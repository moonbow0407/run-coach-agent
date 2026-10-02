"""Eval 数据库守卫的 focused tests（PHASE 6 §11 / §23.1）。"""

import pytest

from app.evals.environment import (
    EVAL_DATABASE_NAME,
    load_eval_settings,
    validate_eval_database_url,
)
from app.evals.errors import EvalEnvironmentError
from app.infrastructure.config import Settings

_SAFE = f"postgresql+asyncpg://postgres:pw@localhost:5432/{EVAL_DATABASE_NAME}"


def _settings(database_url: str) -> Settings:
    return Settings(database_url=database_url, jwt_secret="x" * 32)


def test_guard_accepts_eval_database() -> None:
    """独立 run_coach_eval 数据库通过校验。"""
    settings = _settings("postgresql+asyncpg://postgres:pw@localhost:5432/run_coach")
    validate_eval_database_url(_SAFE, settings=settings)


def test_guard_rejects_wrong_database_name() -> None:
    """库名不是 run_coach_eval 一律拒绝。"""
    settings = _settings("postgresql+asyncpg://postgres:pw@localhost:5432/run_coach")
    with pytest.raises(EvalEnvironmentError, match="eval_database_name_forbidden"):
        validate_eval_database_url(
            "postgresql+asyncpg://postgres:pw@localhost:5432/run_coach", settings=settings
        )


def test_guard_rejects_production_database_url() -> None:
    """与 DATABASE_URL 指向同一目标的连接串拒绝。"""
    settings = _settings(_SAFE)
    with pytest.raises(EvalEnvironmentError, match="conflicts_with_DATABASE_URL"):
        validate_eval_database_url(_SAFE, settings=settings)


def test_guard_rejects_test_database_url(monkeypatch) -> None:
    """与 TEST_DATABASE_URL 指向同一目标的连接串拒绝。"""
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE)
    settings = _settings("postgresql+asyncpg://postgres:pw@localhost:5432/run_coach")
    with pytest.raises(EvalEnvironmentError, match="conflicts_with_TEST_DATABASE_URL"):
        validate_eval_database_url(_SAFE, settings=settings)


def test_guard_rejects_unparseable_url() -> None:
    """无法解析的连接串拒绝。"""
    settings = _settings("postgresql+asyncpg://postgres:pw@localhost:5432/run_coach")
    with pytest.raises(EvalEnvironmentError, match="unparseable"):
        validate_eval_database_url("://not-a-url", settings=settings)


def test_load_eval_settings_requires_env(monkeypatch) -> None:
    """缺少 EVAL_DATABASE_URL 时立即失败，不静默回退。"""
    monkeypatch.delenv("EVAL_DATABASE_URL", raising=False)
    with pytest.raises(EvalEnvironmentError):
        load_eval_settings()


def test_password_never_appears_in_error_message() -> None:
    """守卫错误信息不携带含密码的原始连接串。"""
    settings = _settings("postgresql+asyncpg://postgres:pw@localhost:5432/run_coach")
    with pytest.raises(EvalEnvironmentError) as excinfo:
        validate_eval_database_url(
            "postgresql+asyncpg://postgres:pw@localhost:5432/run_coach", settings=settings
        )
    assert "pw@" not in str(excinfo.value)
