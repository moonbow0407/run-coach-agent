"""agent run checkpoints for mid-run resume

Revision ID: 0007_agent_checkpoints
Revises: 0006_feedback_unique
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_agent_checkpoints"
down_revision: str | Sequence[str] | None = "0006_feedback_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_run_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("current_input", sa.Text(), nullable=False),
        sa.Column("interactions", postgresql.JSONB(), nullable=False),
        sa.Column("discovered_tool_names", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "step_index", name="uq_agent_run_checkpoints_run_step"
        ),
    )
    op.create_index(
        "ix_agent_run_checkpoints_run_id", "agent_run_checkpoints", ["run_id"]
    )
    op.create_index(
        "ix_agent_run_checkpoints_user_id", "agent_run_checkpoints", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_checkpoints_user_id", table_name="agent_run_checkpoints")
    op.drop_index("ix_agent_run_checkpoints_run_id", table_name="agent_run_checkpoints")
    op.drop_table("agent_run_checkpoints")
