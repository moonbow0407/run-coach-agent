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
    event_id: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    trace_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventConsumptionRow(Base):
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

    consumer_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    consumer_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
