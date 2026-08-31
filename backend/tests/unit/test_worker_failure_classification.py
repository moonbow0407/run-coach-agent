"""Worker boundary 对数据库故障的窄类型分类。"""

from sqlalchemy.exc import IntegrityError, OperationalError

from app.workers.consumer import _classify


def test_postgres_operational_error_is_retryable() -> None:
    error = OperationalError("query", {}, RuntimeError("connection refused"))
    assert _classify(error) == ("database_temporarily_unavailable", True)


def test_database_constraint_error_is_permanent() -> None:
    error = IntegrityError("insert", {}, RuntimeError("unique violation"))
    assert _classify(error) == ("database_constraint_error", False)
