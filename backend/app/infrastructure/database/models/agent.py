"""agent 逻辑域的 ORM 表：threads / turns / messages / agent_runs / run_steps。

对应“用户真正经历了什么”与“Agent 当时如何执行”两类事实；
与业务规则相关的约束尽量交给数据库唯一索引 / 条件索引兜底。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class ThreadRow(Base):
    """对话线程表。"""

    __tablename__ = "threads"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TurnRow(Base):
    """一轮交互表：状态 pending/running/committed/failed/cancelled 是对话的事务边界。"""

    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_thread_started_at", "thread_id", "started_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # 不与 messages 建立双向 FK，避免 Turn 与 Message 循环依赖。
    user_message_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageRow(Base):
    """消息表：只存 user / assistant 两种角色，工具调用与观察不写入本表。"""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_thread_created_at", "thread_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id"), nullable=False, index=True)
    turn_id: Mapped[UUID] = mapped_column(ForeignKey("turns.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunRow(Base):
    """一次 Agent 执行表：与 Turn 一一对应，记录执行视角的状态与时间。"""

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    turn_id: Mapped[UUID] = mapped_column(ForeignKey("turns.id"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunStepRow(Base):
    """执行轨迹表：按 (run_id, index) 唯一排序记录每一步推理 / 调用 / 观察。"""

    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "index", name="uq_run_steps_run_index"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    call_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
