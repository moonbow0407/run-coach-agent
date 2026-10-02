"""phase3 coaching intelligence

Revision ID: 0003_phase3
Revises: 0002_phase2_tool_kind
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase3"
down_revision: str | Sequence[str] | None = "0002_phase2_tool_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "athlete_state_snapshots",
        sa.Column("training_load_coverage", sa.Float(), nullable=True),
    )
    op.add_column(
        "athlete_state_snapshots",
        sa.Column(
            "signals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_unique_constraint(
        "uq_training_plans_user_version",
        "training_plans",
        ["user_id", "version"],
    )
    op.create_table(
        "plan_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "from_plan_id",
            sa.Uuid(),
            sa.ForeignKey("training_plans.id"),
            nullable=False,
        ),
        sa.Column("from_plan_version", sa.Integer(), nullable=False),
        sa.Column(
            "based_on_state_id",
            sa.Uuid(),
            sa.ForeignKey("athlete_state_snapshots.id"),
            nullable=False,
        ),
        sa.Column("based_on_state_version", sa.Integer(), nullable=False),
        sa.Column("source_turn_id", sa.Uuid(), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resulting_plan_id",
            sa.Uuid(),
            sa.ForeignKey("training_plans.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_plan_changes_user_id", "plan_changes", ["user_id"])
    op.create_index(
        "ix_plan_changes_user_status_created",
        "plan_changes",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "uq_plan_changes_user_unresolved",
        "plan_changes",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'pending_confirmation')"),
    )


def downgrade() -> None:
    op.drop_index("uq_plan_changes_user_unresolved", table_name="plan_changes")
    op.drop_index("ix_plan_changes_user_status_created", table_name="plan_changes")
    op.drop_index("ix_plan_changes_user_id", table_name="plan_changes")
    op.drop_table("plan_changes")
    op.drop_constraint("uq_training_plans_user_version", "training_plans", type_="unique")
    op.drop_column("athlete_state_snapshots", "signals")
    op.drop_column("athlete_state_snapshots", "training_load_coverage")
