"""unique workout feedback per user+workout

Revision ID: 0006_feedback_unique
Revises: 0005_phase5
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_feedback_unique"
down_revision: str | Sequence[str] | None = "0005_phase5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 先删重复行，保留每个 (user_id, workout_id) 最新 updated_at / created_at 的一条。
    op.execute(
        """
        DELETE FROM workout_feedback AS wf
        USING workout_feedback AS newer
        WHERE wf.user_id = newer.user_id
          AND wf.workout_id = newer.workout_id
          AND wf.id <> newer.id
          AND (
            newer.updated_at > wf.updated_at
            OR (newer.updated_at = wf.updated_at AND newer.created_at > wf.created_at)
            OR (
              newer.updated_at = wf.updated_at
              AND newer.created_at = wf.created_at
              AND newer.id > wf.id
            )
          )
        """
    )
    op.create_unique_constraint(
        "uq_workout_feedback_user_workout",
        "workout_feedback",
        ["user_id", "workout_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workout_feedback_user_workout",
        "workout_feedback",
        type_="unique",
    )
