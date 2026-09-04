"""Eval 运行环境：数据库守卫、migration、重置与按执行方式构建容器。

安全不变量（PHASE 6 §11）：只允许操作名为 run_coach_eval 的独立数据库，
且必须与生产 DATABASE_URL、测试 TEST_DATABASE_URL 都不同；任何校验失败
立即报错，日志不输出含密码的原始连接串。
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evals.errors import EvalEnvironmentError
from app.infrastructure.config import Settings
from app.infrastructure.database.base import Base

EVAL_DATABASE_NAME = "run_coach_eval"  # Eval 专用数据库名；其他名字一律拒绝
EVAL_DATABASE_URL_ENV = "EVAL_DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class EvalClock:
    """可推进的 Eval 时钟：Runner / Fixture 按业务时间逐轮推进。"""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise EvalEnvironmentError("eval_clock_requires_timezone")
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance_to(self, moment: datetime) -> None:
        """把业务时间推进到指定时刻；不允许时间倒流（保证事件顺序确定）。"""
        if moment.tzinfo is None:
            raise EvalEnvironmentError("eval_clock_requires_timezone")
        if moment < self._moment:
            raise EvalEnvironmentError("eval_clock_cannot_move_backwards")
        self._moment = moment


def resolve_eval_database_url() -> str:
    """读取 EVAL_DATABASE_URL 环境变量；缺失立即失败。"""
    value = os.environ.get(EVAL_DATABASE_URL_ENV)
    if not value:
        raise EvalEnvironmentError(
            f"环境变量 {EVAL_DATABASE_URL_ENV} 未设置：Eval 只能运行在独立的 run_coach_eval 数据库"
        )
    return value


def load_base_settings() -> Settings:
    """加载 .env 原始配置（DATABASE_URL 仍是业务库）：仅供防误连比较使用。"""
    try:
        return Settings()
    except ValidationError as exc:
        raise EvalEnvironmentError("eval_settings_invalid") from exc


def load_eval_settings(*, model_override: str | None = None) -> Settings:
    """加载基础配置（.env）并强制替换数据库为 Eval 库；--model 覆盖本次模型。"""
    base = load_base_settings()
    return base.model_copy(
        update={
            "database_url": resolve_eval_database_url(),
            "llm_model": model_override or base.llm_model,
        }
    )


def _normalized_target(url: str) -> tuple[str, str | None, str | None, int | None, str | None]:
    """连接串归一化：只比较 dialect/用户/主机/端口/库名，不含密码与查询参数。"""
    parsed = make_url(url)
    return (parsed.drivername, parsed.username, parsed.host, parsed.port, parsed.database)


def validate_eval_database_url(eval_url: str, *, settings: Settings) -> None:
    """migration / 清理前的严格防误连校验；任何条件不满足立即 ERROR。

    错误信息只描述失败原因，不携带含密码的原始连接串。
    """
    try:
        parsed = make_url(eval_url)
    except Exception as exc:
        raise EvalEnvironmentError("eval_database_url_unparseable") from exc
    if parsed.database != EVAL_DATABASE_NAME:
        raise EvalEnvironmentError(f"eval_database_name_forbidden: 只允许 {EVAL_DATABASE_NAME}")
    if _normalized_target(eval_url) == _normalized_target(settings.database_url):
        raise EvalEnvironmentError("eval_database_url_conflicts_with_DATABASE_URL")
    test_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if test_url and _normalized_target(eval_url) == _normalized_target(test_url):
        raise EvalEnvironmentError("eval_database_url_conflicts_with_TEST_DATABASE_URL")


async def verify_connected_database(engine: AsyncEngine) -> None:
    """实际连接后再次确认 current_database() 是 Eval 专用库。"""
    async with engine.connect() as connection:
        current = await connection.scalar(text("SELECT current_database()"))
    if current != EVAL_DATABASE_NAME:
        raise EvalEnvironmentError(f"eval_database_connected_wrong_target: {current!r}")


async def upgrade_eval_schema(database_url: str) -> None:
    """用正式 Alembic revision 迁移 Eval 库；同步命令放线程池避免阻塞事件循环。"""
    config = AlembicConfig(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)

    def _upgrade() -> None:
        alembic_command.upgrade(config, "head")

    await asyncio.to_thread(_upgrade)


async def reset_eval_database(engine: AsyncEngine) -> None:
    """TRUNCATE 全部应用表；执行前再次确认连接目标就是 run_coach_eval。"""
    await verify_connected_database(engine)
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
