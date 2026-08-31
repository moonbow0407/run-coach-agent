"""Phase 4 长期记忆 ORM：Memory 是派生认知，不复制 canonical facts。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base

EMBEDDING_DIMENSIONS = 1536


class SemanticMemoryRow(Base):
    __tablename__ = "semantic_memories"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_memory_validity",
        ),
        Index("ix_semantic_user_status_type_valid", "user_id", "status", "type", "valid_from"),
        Index(
            "ix_semantic_user_knowledge_time",
            "user_id",
            "activated_at",
            "superseded_at",
            "expired_at",
        ),
        Index("ix_semantic_user_slot", "user_id", "type", "subject_key", "status"),
        Index(
            "uq_semantic_user_active_slot",
            "user_id",
            "type",
            "subject_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_semantic_user_live_assertion",
            "user_id",
            "assertion_hash",
            unique=True,
            postgresql_where=text("status IN ('candidate', 'active')"),
        ),
        Index(
            "ix_semantic_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    content: Mapped[str] = mapped_column(String(240), nullable=False)
    assertion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    projector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("semantic_memories.id"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryEvidenceRow(Base):
    __tablename__ = "memory_evidence"
    __table_args__ = (
        UniqueConstraint(
            "memory_id", "source_type", "source_id", "role", name="uq_memory_evidence_source_role"
        ),
        Index("ix_memory_evidence_source", "user_id", "source_type", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("semantic_memories.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_group_key: Mapped[str] = mapped_column(String(200), nullable=False)
    independence_role: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EpisodeRow(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ck_episode_range"),
        CheckConstraint("importance >= 0 AND importance <= 1", name="ck_episode_importance"),
        UniqueConstraint("user_id", "type", "logical_key", name="uq_episode_logical_identity"),
        Index("ix_episode_user_status_type_ended", "user_id", "status", "type", "ended_at"),
        Index(
            "ix_episode_user_knowledge_time",
            "user_id",
            "completed_at",
            "superseded_at",
            "ended_at",
        ),
        Index(
            "ix_episode_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    projector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    projector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(200), nullable=False)
    superseded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("episodes.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EpisodeEvidenceRow(Base):
    __tablename__ = "episode_evidence"
    __table_args__ = (
        UniqueConstraint(
            "episode_id", "source_type", "source_id", "role", name="uq_episode_evidence_source_role"
        ),
        Index("ix_episode_evidence_source", "user_id", "source_type", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    episode_id: Mapped[UUID] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryProjectionRunRow(Base):
    __tablename__ = "memory_projection_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "projector_name",
            "projector_version",
            "projection_key",
            name="uq_memory_projection_identity",
        ),
        Index("ix_memory_projection_status_started", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    projector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    projector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_key: Mapped[str] = mapped_column(String(240), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
