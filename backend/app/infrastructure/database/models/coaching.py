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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 训练归属的跑者
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 训练开始时间
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)  # 训练距离（米）；设备未上报为空
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 训练时长（秒）
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 平均心率（次/分）
    max_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 最大心率（次/分）
    workout_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 课种：easy/tempo/interval/long_run/rest/race/other
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # 数据来源：seed（种子数据）/ manual（手工录入）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 落库时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最后更新时间


class WorkoutFeedbackRow(Base):
    """用户对某次训练的主观反馈（自感用力 / 疲劳 / 酸痛 / 备注），量表统一 1–10。"""

    __tablename__ = "workout_feedback"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workout_id",
            name="uq_workout_feedback_user_workout",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 反馈归属的跑者
    workout_id: Mapped[UUID] = mapped_column(ForeignKey("workouts.id"), nullable=False, index=True)  # 反馈针对的训练
    perceived_exertion: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 自感用力度（RPE，1–10）；未报告为空
    subjective_fatigue: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 主观疲劳度（1–10）；未报告为空
    soreness: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 酸痛程度（1–10）；未报告为空
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 用户文字备注
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 反馈提交时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最后更新时间


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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 目标归属的跑者
    goal_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 目标类型：race（备赛）/ general（一般提升）
    race_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 比赛日期；非比赛目标为空
    race_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 比赛距离（米）
    target_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 目标完赛时间（秒）
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 目标状态：active/completed/cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 目标创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 最后更新时间


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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 计划归属的跑者
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # 计划版本号；调整生成新版本，不覆盖历史
    goal_id: Mapped[UUID | None] = mapped_column(ForeignKey("training_goals.id"), nullable=True)  # 服务的训练目标；无目标计划为空
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 计划状态：active/superseded/completed/cancelled
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)  # 计划起始日
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)  # 计划结束日
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 版本创建时间


class PlannedSessionRow(Base):
    """计划内的单次课次，prescription 存结构化处方（JSONB）。"""

    __tablename__ = "planned_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("training_plans.id"), nullable=False, index=True)  # 所属训练计划版本
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)  # 计划训练日期
    session_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 课种：easy/tempo/interval/long_run/rest/race/other
    title: Mapped[str] = mapped_column(String(200), nullable=False)  # 课次标题（如“有氧 40 分钟”）
    prescription: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 结构化训练处方（距离/配速等）


class AthleteStateSnapshotRow(Base):
    """跑者状态快照：只插入新版本，不 UPDATE 旧行；(user_id, version) 唯一。"""

    __tablename__ = "athlete_state_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_athlete_state_user_version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 快照归属的跑者
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # 快照版本号；只追加新版本，永不 UPDATE 旧行
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 状态评估的时间切点
    fatigue_level: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 疲劳等级：low/moderate/high；证据不足为空
    recovery_level: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 恢复等级：poor/fair/good；证据不足为空
    recent_training_load: Mapped[float | None] = mapped_column(Float, nullable=True)  # 近期可用 sRPE 训练负荷
    workout_completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 计划课次完成率（预留字段，当前算法不产出）
    training_load_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)  # sRPE 覆盖率：有反馈课次占比，过低则负荷不可信
    signals: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )  # 结构化状态依据列表（code/severity/message/证据引用）
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 本次评估置信度 0–1
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)  # 产出快照的评估算法版本
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 快照落库时间


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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # 提案归属的跑者
    from_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("training_plans.id"), nullable=False
    )  # 调整前的计划
    from_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)  # 调整前计划的版本号
    based_on_state_id: Mapped[UUID] = mapped_column(
        ForeignKey("athlete_state_snapshots.id"), nullable=False
    )  # 提案依据的跑者状态快照
    based_on_state_version: Mapped[int] = mapped_column(Integer, nullable=False)  # 依据快照的版本号
    source_turn_id: Mapped[UUID | None] = mapped_column(nullable=True)  # 触发提案的对话轮次（系统评估生成为空）
    source_run_id: Mapped[UUID | None] = mapped_column(nullable=True)  # 触发提案的 Agent Run
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 提案生成时间切点
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)  # 调整类型（如 reduce_upcoming_load）
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 结构化改动明细（horizon + 课次替换列表）
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # 调整理由，面向用户解释
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 提案状态机：draft/pending_confirmation/confirmed/rejected/stale/abandoned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 提案创建时间
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 提案被确认/拒绝的时间；未处理为空
    resulting_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("training_plans.id"), nullable=True
    )  # 确认后生成的新计划；未确认为空
