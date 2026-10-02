"""phase5 continuous state and workers

Revision ID: 0005_phase5
Revises: 0004_phase4
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase5"
down_revision: str | Sequence[str] | None = "0004_phase4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE workouts SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("workouts", "updated_at", nullable=False)
    op.add_column(
        "workout_feedback",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE workout_feedback SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("workout_feedback", "updated_at", nullable=False)

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(120), nullable=True),
        sa.Column("claim_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'quarantined')", name="ck_outbox_status"
        ),
        sa.CheckConstraint("publish_attempt_count >= 0", name="ck_outbox_attempt_count"),
        sa.CheckConstraint(
            "(claimed_by IS NULL AND claim_until IS NULL) OR "
            "(claimed_by IS NOT NULL AND claim_until IS NOT NULL)",
            name="ck_outbox_claim_lease",
        ),
    )
    op.create_index("ix_outbox_events_user_id", "outbox_events", ["user_id"])
    op.create_index(
        "ix_outbox_status_available_created",
        "outbox_events",
        ["status", "available_at", "created_at"],
    )
    op.create_index("ix_outbox_user_occurred", "outbox_events", ["user_id", "occurred_at"])
    op.create_index(
        "ix_outbox_pending_claim_until",
        "outbox_events",
        ["claim_until"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "event_consumptions",
        sa.Column("consumer_name", sa.String(100), primary_key=True),
        sa.Column("consumer_version", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'dead_lettered')",
            name="ck_event_consumption_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_event_consumption_attempt_count"),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_until IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_event_consumption_lease",
        ),
    )
    op.create_index(
        "ix_event_consumption_status_lease",
        "event_consumptions",
        ["status", "lease_until"],
    )
    op.create_index(
        "ix_event_consumption_user_started",
        "event_consumptions",
        ["user_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("event_consumptions")
    op.drop_table("outbox_events")
    op.drop_column("workout_feedback", "updated_at")
    op.drop_column("workouts", "updated_at")
