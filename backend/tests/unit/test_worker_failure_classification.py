"""Worker boundary 对数据库故障的窄类型分类。"""

from sqlalchemy.exc import IntegrityError, OperationalError

from app.workers.consumer import _classify


def test_postgres_operational_error_is_retryable() -> None:
    """验证：连接拒绝等瞬时故障归为 database_temporarily_unavailable 且可重试。"""
    error = OperationalError("query", {}, RuntimeError("connection refused"))
    assert _classify(error) == ("database_temporarily_unavailable", True)


def test_database_constraint_error_is_permanent() -> None:
    """验证：约束冲突归为永久失败——重试也无意义，不进入延迟重试。"""
    error = IntegrityError("insert", {}, RuntimeError("unique violation"))
    assert _classify(error) == ("database_constraint_error", False)
