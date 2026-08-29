"""phase1 initial schema

Revision ID: 0001_phase1
Revises:
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase1"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workouts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("avg_heart_rate", sa.Integer(), nullable=True),
        sa.Column("max_heart_rate", sa.Integer(), nullable=True),
        sa.Column("workout_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workouts_user_id", "workouts", ["user_id"])
    op.create_index("ix_workouts_user_started_at", "workouts", ["user_id", "started_at"])
    op.create_table(
        "workout_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workout_id", sa.Uuid(), sa.ForeignKey("workouts.id"), nullable=False),
        sa.Column("perceived_exertion", sa.Integer(), nullable=True),
        sa.Column("subjective_fatigue", sa.Integer(), nullable=True),
        sa.Column("soreness", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workout_feedback_user_id", "workout_feedback", ["user_id"])
    op.create_index("ix_workout_feedback_workout_id", "workout_feedback", ["workout_id"])
    op.create_table(
        "training_goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("goal_type", sa.String(32), nullable=False),
        sa.Column("race_date", sa.Date(), nullable=True),
        sa.Column("race_distance_m", sa.Integer(), nullable=True),
        sa.Column("target_time_s", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_training_goals_user_id", "training_goals", ["user_id"])
    op.create_index(
        "uq_training_goals_user_active",
        "training_goals",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "training_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("training_goals.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_training_plans_user_id", "training_plans", ["user_id"])
    op.create_index(
        "uq_training_plans_user_active",
        "training_plans",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "planned_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("training_plans.id"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("session_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("prescription", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_planned_sessions_plan_id", "planned_sessions", ["plan_id"])
    op.create_table(
        "athlete_state_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fatigue_level", sa.String(32), nullable=True),
        sa.Column("recovery_level", sa.String(32), nullable=True),
        sa.Column("recent_training_load", sa.Float(), nullable=True),
        sa.Column("workout_completion_rate", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "version", name="uq_athlete_state_user_version"),
    )
    op.create_index("ix_athlete_state_snapshots_user_id", "athlete_state_snapshots", ["user_id"])
    op.create_table(
        "threads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_threads_user_id", "threads", ["user_id"])
    op.create_table(
        "turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("thread_id", sa.Uuid(), sa.ForeignKey("threads.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_turns_thread_id", "turns", ["thread_id"])
    op.create_index("ix_turns_user_id", "turns", ["user_id"])
    op.create_index("ix_turns_thread_started_at", "turns", ["thread_id", "started_at"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("thread_id", sa.Uuid(), sa.ForeignKey("threads.id"), nullable=False),
        sa.Column("turn_id", sa.Uuid(), sa.ForeignKey("turns.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])
    op.create_index("ix_messages_turn_id", "messages", ["turn_id"])
    op.create_index("ix_messages_thread_created_at", "messages", ["thread_id", "created_at"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("turn_id", sa.Uuid(), sa.ForeignKey("turns.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_turn_id", "agent_runs", ["turn_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_table(
        "run_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "index", name="uq_run_steps_run_index"),
    )
    op.create_index("ix_run_steps_run_id", "run_steps", ["run_id"])
    op.create_index("ix_run_steps_call_id", "run_steps", ["call_id"])


def downgrade() -> None:
    op.drop_table("run_steps")
    op.drop_table("agent_runs")
    op.drop_table("messages")
    op.drop_table("turns")
    op.drop_table("threads")
    op.drop_table("athlete_state_snapshots")
    op.drop_table("planned_sessions")
    op.drop_table("training_plans")
    op.drop_table("training_goals")
    op.drop_table("workout_feedback")
    op.drop_table("workouts")
    op.drop_table("users")
