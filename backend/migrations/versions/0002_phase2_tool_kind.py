"""phase2 tool call kind normalization

Revision ID: 0002_phase2_tool_kind
Revises: 0001_phase1
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_phase2_tool_kind"
down_revision: str | Sequence[str] | None = "0001_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 2 起 RunStep kind 使用 tool_call；把历史 capability_call 一次性归一化。
    # 运行时代码不再理解旧值；不新增任何表。
    op.execute("UPDATE run_steps SET kind = 'tool_call' WHERE kind = 'capability_call'")


def downgrade() -> None:
    op.execute(
        "UPDATE run_steps SET kind = 'capability_call' WHERE kind = 'tool_call'"
    )
