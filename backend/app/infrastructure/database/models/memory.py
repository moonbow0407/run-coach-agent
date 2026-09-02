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

EMBEDDING_DIMENSIONS = 1536  # embedding 维度：pgvector 列与配置口径保持一致


class SemanticMemoryRow(Base):
    """语义记忆表：关于用户的稳定事实断言（偏好/约束/模式），带完整生命周期。"""

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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 记忆归属的用户
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # 记忆类型：可用性约束/训练偏好/恢复模式等
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # 来源方式：explicit（用户明说）/ inferred（系统推断）
    subject_key: Mapped[str] = mapped_column(String(120), nullable=False)  # 断言主体键（如 sleep:duration），与 type 定位同一记忆槽位
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)  # 断言值（JSON 标量/元组/字典）
    content: Mapped[str] = mapped_column(String(240), nullable=False)  # 面向 LLM 的自然语言表述（≤240 字）
    assertion_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # 断言身份哈希（type+subject_key+value），防重复断言
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 置信度 0–1：明示为 1.0，推断随独立证据组增加
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # 生命周期：candidate/active/superseded/expired
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 断言开始有效时间
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 失效时间；长期有效为空
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 进入 active 的时间
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 过期时间
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 证据中最晚的事实发生时间
    projector_name: Mapped[str] = mapped_column(String(100), nullable=False)  # 产出该记忆的投影器名称
    projector_version: Mapped[str] = mapped_column(String(64), nullable=False)  # 投影器版本，用于按版本重投影
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)  # 生成向量的 embedding 模型名
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)  # embedding 版本号
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)  # 语义向量，HNSW 索引支持相似检索
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("semantic_memories.id"), nullable=True
    )  # 取代本条的新记忆 ID
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 被取代时间
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 落库时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最后更新时间


class MemoryEvidenceRow(Base):
    """语义记忆的证据表：记录每条记忆由哪些业务事实支撑，保证可溯源。"""

    __tablename__ = "memory_evidence"
    __table_args__ = (
        UniqueConstraint(
            "memory_id", "source_type", "source_id", "role", name="uq_memory_evidence_source_role"
        ),
        Index("ix_memory_evidence_source", "user_id", "source_type", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)  # 归属用户
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("semantic_memories.id"), nullable=False, index=True
    )  # 证据支撑的语义记忆
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)  # 来源类型：消息/训练/反馈/快照/计划调整等
    source_id: Mapped[UUID] = mapped_column(nullable=False)  # 来源记录的 ID
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 来源事实的发生时间
    evidence_group_key: Mapped[str] = mapped_column(String(200), nullable=False)  # 证据分组键；同组证据只算一个独立来源
    independence_role: Mapped[str] = mapped_column(String(32), nullable=False)  # 独立性角色：primary（独立证据）/ derived_context（派生上下文）
    role: Mapped[str] = mapped_column(String(24), nullable=False)  # 证据立场：supports（支持）/ corrects（修正）/ contradicts（矛盾）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 落库时间


class EpisodeRow(Base):
    """情节记忆表：一段有起止的训练经历（疲劳恢复过程/计划调整效果）。"""

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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 情节归属的用户
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # 情节类型：fatigue_and_recovery / plan_adaptation_outcome
    summary: Mapped[str] = mapped_column(String(500), nullable=False)  # 情节摘要（≤500 字）
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 情节开始时间
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 情节结束时间
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 完成时间；出现 outcome 证据才算完成
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 被取代时间
    importance: Mapped[float] = mapped_column(Float, nullable=False)  # 情节重要性 0–1
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # 状态：building（构建中）/ completed / superseded
    projector_name: Mapped[str] = mapped_column(String(100), nullable=False)  # 产出该情节的投影器名称
    projector_version: Mapped[str] = mapped_column(String(64), nullable=False)  # 投影器版本，用于按版本重投影
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)  # 生成向量的 embedding 模型名
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)  # embedding 版本号
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)  # 语义向量，HNSW 索引支持相似检索
    logical_key: Mapped[str] = mapped_column(String(200), nullable=False)  # 逻辑身份键（与 user/type 联合唯一，防止重复情节）
    superseded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("episodes.id"), nullable=True)  # 取代本条的新情节 ID
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 落库时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最后更新时间


class EpisodeEvidenceRow(Base):
    """情节证据表：记录构成情节的触发/上下文/干预/结果四类事实。"""

    __tablename__ = "episode_evidence"
    __table_args__ = (
        UniqueConstraint(
            "episode_id", "source_type", "source_id", "role", name="uq_episode_evidence_source_role"
        ),
        Index("ix_episode_evidence_source", "user_id", "source_type", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)  # 归属用户
    episode_id: Mapped[UUID] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)  # 证据所属的情节
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)  # 来源类型：消息/训练/反馈/计划调整等
    source_id: Mapped[UUID] = mapped_column(nullable=False)  # 来源记录的 ID
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 来源事实的发生时间
    role: Mapped[str] = mapped_column(String(24), nullable=False)  # 证据角色：trigger（触发）/ context（上下文）/ intervention（干预）/ outcome（结果）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 落库时间


class MemoryProjectionRunRow(Base):
    """记忆投影运行记录：读模型投影的幂等执行台账（projection=读模型投影）。"""

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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 投影归属的用户
    projector_name: Mapped[str] = mapped_column(String(100), nullable=False)  # 投影器名称
    projector_version: Mapped[str] = mapped_column(String(64), nullable=False)  # 投影器版本
    projection_key: Mapped[str] = mapped_column(String(240), nullable=False)  # 投影键；与名称/版本联合唯一定位一次投影
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)  # 输入指纹：相同指纹直接复用结果，保证幂等
    input_checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 输入检查点（如上次处理到的事件位置）
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # 运行状态（进行中/成功/失败）
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 结果摘要（写入/失效/跳过条数等）
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 失败错误码；成功为空
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 开始时间
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 完成时间；未完成为空
