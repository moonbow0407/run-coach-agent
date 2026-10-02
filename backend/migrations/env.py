import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.infrastructure.database import models as _models  # noqa: F401
from app.infrastructure.database.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 连接串不写入 alembic.ini（公开仓库，防止凭据泄露），在此按优先级解析：
# 1. 调用方显式注入的 sqlalchemy.url——集成测试用它指向 run_coach_test，
#    绝不能被本机 .env 中的应用库地址覆盖；
# 2. DATABASE_URL 环境变量；
# 3. 根目录与 backend 下的 .env（先加载根目录，后加载者不覆盖，与应用
#    Settings 的 env_file=(".env", "../.env") 语义一致）。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
database_url = config.get_main_option("sqlalchemy.url") or os.getenv("DATABASE_URL")
if not database_url:
    load_dotenv(BACKEND_ROOT.parent / ".env")
    load_dotenv(BACKEND_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "数据库连接未配置：请设置 DATABASE_URL 环境变量，"
        "或复制 .env.example 为 backend/.env 并填写 DATABASE_URL"
    )
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
