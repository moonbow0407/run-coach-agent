"""coaching 逻辑域的 ORM 表：训练事实 / 目标 / 计划 / 跑者状态快照。

这些表是 PostgreSQL 中的 Canonical State（Source of Truth）。
每个用户同时最多只有一个 active 目标与 active 计划，用部分唯一索引强制。
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class WorkoutRow(Base):
    """一次真实训练记录（距离 / 时长 / 心率 / 类型等）。"""

    __tablename__ = "workouts"
    __table_args__ = (Index("ix_workouts_user_started_at", "user_id", "started_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workout_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkoutFeedbackRow(Base):
    """用户对某次训练的主观反馈（自感用力 / 疲劳 / 酸痛 / 备注），量表统一 1–10。"""

    __tablename__ = "workout_feedback"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    workout_id: Mapped[UUID] = mapped_column(ForeignKey("workouts.id"), nullable=False, index=True)
    perceived_exertion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subjective_fatigue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soreness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrainingGoalRow(Base):
    """训练目标。部分唯一索引保证每个用户至多一个 active 目标。"""

    __tablename__ = "training_goals"
    __table_args__ = (
        Index(
            "uq_training_goals_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    goal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    race_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    race_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrainingPlanRow(Base):
    """版本化训练计划。部分唯一索引保证每个用户至多一个 active 计划版本。"""

    __tablename__ = "training_plans"
    __table_args__ = (
        Index(
            "uq_training_plans_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        UniqueConstraint("user_id", "version", name="uq_training_plans_user_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_id: Mapped[UUID | None] = mapped_column(ForeignKey("training_goals.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlannedSessionRow(Base):
    """计划内的单次课次，prescription 存结构化处方（JSONB）。"""

    __tablename__ = "planned_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("training_plans.id"), nullable=False, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    prescription: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AthleteStateSnapshotRow(Base):
    """跑者状态快照：只插入新版本，不 UPDATE 旧行；(user_id, version) 唯一。"""

    __tablename__ = "athlete_state_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_athlete_state_user_version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fatigue_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recovery_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recent_training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    workout_completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    signals: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanChangeRow(Base):
    """计划调整提案。部分唯一约束保证同一用户最多一个未解决提案。"""

    __tablename__ = "plan_changes"
    __table_args__ = (
        Index("ix_plan_changes_user_status_created", "user_id", "status", "created_at"),
        Index(
            "uq_plan_changes_user_unresolved",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'pending_confirmation')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    from_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("training_plans.id"), nullable=False
    )
    from_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    based_on_state_id: Mapped[UUID] = mapped_column(
        ForeignKey("athlete_state_snapshots.id"), nullable=False
    )
    based_on_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_turn_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resulting_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("training_plans.id"), nullable=True
    )
