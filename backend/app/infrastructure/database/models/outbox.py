"""Phase 5 Outbox 与 consumer outcome ORM。

Outbox 保存待发布的 durable business event；event_consumptions 保存 consumer
处理结果。它们都不是 Redis queue job，也不承载领域事实本身。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class OutboxEventRow(Base):
    """outbox=本地消息表：业务事务内落库的待发布事件，后台轮询投递到 Redis/arq 队列。"""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'published', 'quarantined')",
            name="ck_outbox_status",
        ),
        CheckConstraint("publish_attempt_count >= 0", name="ck_outbox_attempt_count"),
        CheckConstraint(
            "(claimed_by IS NULL AND claim_until IS NULL) OR "
            "(claimed_by IS NOT NULL AND claim_until IS NOT NULL)",
            name="ck_outbox_claim_lease",
        ),
        Index("ix_outbox_status_available_created", "status", "available_at", "created_at"),
        Index("ix_outbox_user_occurred", "user_id", "occurred_at"),
        Index(
            "ix_outbox_pending_claim_until",
            "claim_until",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column(unique=True, nullable=False)  # 业务事件全局唯一 ID
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)  # 事件类型名（如 workout.recorded）
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)  # 事件载荷 schema 版本
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)  # 事件所属聚合类型（训练/计划等）
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)  # 聚合根记录 ID
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 事件归属用户
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 业务事实发生时间
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 事件载荷（JSONB）
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)  # 关联 ID：串起同一业务流程的多条事件
    causation_id: Mapped[UUID | None] = mapped_column(nullable=True)  # 因果 ID：触发本事件的上游事件
    trace_id: Mapped[UUID | None] = mapped_column(nullable=True)  # 链路追踪 ID
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # 投递状态：pending（待发）/ published（已发）/ quarantined（隔离）
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最早可投递时间（支持延迟投递）
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 认领投递任务的投递进程标识
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 认领租约到期时间，到期可被重新认领
    publish_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)  # 已尝试投递次数
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 最近一次投递失败的错误码
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 落库时间
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 成功发布时间
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 进入隔离区时间；多次失败后停止投递


class EventConsumptionRow(Base):
    """consumer receipt=消费回执表：记录消费者对事件的处理状态，用于幂等去重。"""

    __tablename__ = "event_consumptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'dead_lettered')",
            name="ck_event_consumption_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_event_consumption_attempt_count"),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_until IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_event_consumption_lease",
        ),
        Index("ix_event_consumption_status_lease", "status", "lease_until"),
        Index("ix_event_consumption_user_started", "user_id", "started_at"),
    )

    consumer_name: Mapped[str] = mapped_column(String(100), primary_key=True)  # 消费者名称（联合主键之一）
    consumer_version: Mapped[int] = mapped_column(Integer, primary_key=True)  # 消费者逻辑版本（联合主键之一，逻辑变更时递增重放）
    event_id: Mapped[UUID] = mapped_column(primary_key=True)  # 被消费的事件 ID（联合主键之一）
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)  # 事件归属用户
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # 消费状态：processing（处理中）/ completed / dead_lettered（死信）
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)  # 已尝试处理次数
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 持有处理租约的消费者实例
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 租约到期时间，到期可被其他实例接管
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 最近一次失败错误码
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 首次开始处理时间
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 完成时间；未完成为空
