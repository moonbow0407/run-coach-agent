"""agent 逻辑域的 ORM 表：threads / turns / messages / agent_runs / run_steps。

对应“用户真正经历了什么”与“Agent 当时如何执行”两类事实；
与业务规则相关的约束尽量交给数据库唯一索引 / 条件索引兜底。

Mapped[...] / mapped_column 是 SQLAlchemy 2.0 的类型化映射声明：类型注解声明列类型。
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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 线程归属的跑者
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 线程创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最后一次更新时间


class TurnRow(Base):
    """一轮交互表：状态 pending/running/committed/failed/cancelled 是对话的事务边界。"""

    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_thread_started_at", "thread_id", "started_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id"), nullable=False, index=True)  # 所属对话线程
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 归属用户（冗余存储，便于按用户检索）
    # 不与 messages 建立双向 FK，避免 Turn 与 Message 循环依赖。
    user_message_id: Mapped[UUID] = mapped_column(nullable=False)  # 本轮用户消息的 ID
    assistant_message_id: Mapped[UUID | None] = mapped_column(nullable=True)  # 本轮助手回复的 ID，回复落库前为空
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # Turn 状态机：pending/running/committed/failed/cancelled
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 本轮开始时间
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 本轮事务提交时间；失败/取消时为空


class MessageRow(Base):
    """消息表：只存 user / assistant 两种角色，工具调用与观察不写入本表。"""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_thread_created_at", "thread_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id"), nullable=False, index=True)  # 所属对话线程
    turn_id: Mapped[UUID] = mapped_column(ForeignKey("turns.id"), nullable=False, index=True)  # 所属 Turn（一轮对话）
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # 消息角色：user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 消息正文
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 消息落库时间


class AgentRunRow(Base):
    """一次 Agent 执行表：与 Turn 一一对应，记录执行视角的状态与时间。"""

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    turn_id: Mapped[UUID] = mapped_column(ForeignKey("turns.id"), nullable=False, index=True)  # 对应的一轮对话（与 Turn 一一对应）
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 归属用户（冗余存储，便于按用户检索）
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # Run 状态机（执行视角，独立于 Turn 状态）
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # Run 开始时间
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Run 结束时间；未完成为空


class RunStepRow(Base):
    """执行轨迹表：按 (run_id, index) 唯一排序记录每一步推理 / 调用 / 观察。"""

    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "index", name="uq_run_steps_run_index"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), nullable=False, index=True)  # 所属 Run
    index: Mapped[int] = mapped_column(Integer, nullable=False)  # 步骤序号（与 run_id 联合唯一，保证轨迹有序）
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # 步骤类型：reasoning/tool_call/observation/final
    call_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)  # 工具调用 ID，用于把 tool_call 与 observation 配对
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # 步骤输入载荷（JSONB）
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # 步骤输出载荷（JSONB）
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 步骤开始时间
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 步骤结束时间；未完成为空
