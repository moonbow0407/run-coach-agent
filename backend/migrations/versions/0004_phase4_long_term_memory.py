"""phase4 long-term memory

Revision ID: 0004_phase4
Revises: 0003_phase3
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase4"
down_revision: str | Sequence[str] | None = "0003_phase3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "semantic_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(120), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("content", sa.String(240), nullable=False),
        sa.Column("assertion_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projector_name", sa.String(100), nullable=False),
        sa.Column("projector_version", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "superseded_by_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_memories.id"),
            nullable=True,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="ck_memory_validity"
        ),
    )
    op.create_index("ix_semantic_memories_user_id", "semantic_memories", ["user_id"])
    op.create_index(
        "ix_semantic_user_status_type_valid",
        "semantic_memories",
        ["user_id", "status", "type", "valid_from"],
    )
    op.create_index(
        "ix_semantic_user_knowledge_time",
        "semantic_memories",
        ["user_id", "activated_at", "superseded_at", "expired_at"],
    )
    op.create_index(
        "ix_semantic_user_slot",
        "semantic_memories",
        ["user_id", "type", "subject_key", "status"],
    )
    op.create_index(
        "uq_semantic_user_active_slot",
        "semantic_memories",
        ["user_id", "type", "subject_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_semantic_user_live_assertion",
        "semantic_memories",
        ["user_id", "assertion_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('candidate', 'active')"),
    )
    op.execute(
        "CREATE INDEX ix_semantic_embedding_hnsw ON semantic_memories "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "memory_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "memory_id", sa.Uuid(), sa.ForeignKey("semantic_memories.id"), nullable=False
        ),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_group_key", sa.String(200), nullable=False),
        sa.Column("independence_role", sa.String(32), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "memory_id", "source_type", "source_id", "role", name="uq_memory_evidence_source_role"
        ),
    )
    op.create_index("ix_memory_evidence_memory_id", "memory_evidence", ["memory_id"])
    op.create_index(
        "ix_memory_evidence_source",
        "memory_evidence",
        ["user_id", "source_type", "source_id"],
    )

    op.create_table(
        "episodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("projector_name", sa.String(100), nullable=False),
        sa.Column("projector_version", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("logical_key", sa.String(200), nullable=False),
        sa.Column("superseded_by_id", sa.Uuid(), sa.ForeignKey("episodes.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ended_at >= started_at", name="ck_episode_range"),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="ck_episode_importance"),
        sa.UniqueConstraint("user_id", "type", "logical_key", name="uq_episode_logical_identity"),
    )
    op.create_index("ix_episodes_user_id", "episodes", ["user_id"])
    op.create_index(
        "ix_episode_user_status_type_ended",
        "episodes",
        ["user_id", "status", "type", "ended_at"],
    )
    op.create_index(
        "ix_episode_user_knowledge_time",
        "episodes",
        ["user_id", "completed_at", "superseded_at", "ended_at"],
    )
    op.execute(
        "CREATE INDEX ix_episode_embedding_hnsw ON episodes "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "episode_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), sa.ForeignKey("episodes.id"), nullable=False),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "episode_id", "source_type", "source_id", "role", name="uq_episode_evidence_source_role"
        ),
    )
    op.create_index("ix_episode_evidence_episode_id", "episode_evidence", ["episode_id"])
    op.create_index(
        "ix_episode_evidence_source",
        "episode_evidence",
        ["user_id", "source_type", "source_id"],
    )

    op.create_table(
        "memory_projection_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("projector_name", sa.String(100), nullable=False),
        sa.Column("projector_version", sa.String(64), nullable=False),
        sa.Column("projection_key", sa.String(240), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_checkpoint", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result_summary", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "projector_name",
            "projector_version",
            "projection_key",
            name="uq_memory_projection_identity",
        ),
    )
    op.create_index(
        "ix_memory_projection_runs_user_id", "memory_projection_runs", ["user_id"]
    )
    op.create_index(
        "ix_memory_projection_status_started",
        "memory_projection_runs",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("memory_projection_runs")
    op.drop_table("episode_evidence")
    op.drop_table("episodes")
    op.drop_table("memory_evidence")
    op.drop_table("semantic_memories")
