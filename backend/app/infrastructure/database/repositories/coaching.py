from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.goal.models import GoalStatus, TrainingGoal
from app.coaching.domain.plan.models import PlannedSession, PlanStatus, TrainingPlan
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.infrastructure.database.mappers import (
    athlete_state_from_row,
    feedback_from_row,
    goal_from_row,
    plan_from_row,
    session_from_row,
    workout_from_row,
)
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlannedSessionRow,
    TrainingGoalRow,
    TrainingPlanRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.database.session import short_session


class SqlAlchemyWorkoutRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_recent(
        self,
        *,
        user_id: UUID,
        since: datetime,
        limit: int,
    ) -> list[Workout]:
        stmt: Select[tuple[WorkoutRow]] = (
            select(WorkoutRow)
            .where(WorkoutRow.user_id == user_id, WorkoutRow.started_at >= since)
            .order_by(WorkoutRow.started_at.desc())
            .limit(limit)
        )
        async with short_session(self._sessions) as session:
            rows = (await session.scalars(stmt)).all()
            return [workout_from_row(row) for row in rows]

    async def get(self, *, user_id: UUID, workout_id: UUID) -> Workout | None:
        stmt = select(WorkoutRow).where(
            WorkoutRow.id == workout_id,
            WorkoutRow.user_id == user_id,
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return workout_from_row(row) if row else None

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        stmt = select(WorkoutFeedbackRow).where(
            WorkoutFeedbackRow.workout_id == workout_id,
            WorkoutFeedbackRow.user_id == user_id,
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return feedback_from_row(row) if row else None


class SqlAlchemyGoalRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_active(self, *, user_id: UUID) -> TrainingGoal | None:
        stmt = select(TrainingGoalRow).where(
            TrainingGoalRow.user_id == user_id,
            TrainingGoalRow.status == GoalStatus.ACTIVE.value,
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return goal_from_row(row) if row else None


class SqlAlchemyPlanRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_active(self, *, user_id: UUID) -> TrainingPlan | None:
        stmt = select(TrainingPlanRow).where(
            TrainingPlanRow.user_id == user_id,
            TrainingPlanRow.status == PlanStatus.ACTIVE.value,
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return plan_from_row(row) if row else None

    async def list_sessions(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> list[PlannedSession]:
        stmt = (
            select(PlannedSessionRow)
            .join(TrainingPlanRow, TrainingPlanRow.id == PlannedSessionRow.plan_id)
            .where(
                PlannedSessionRow.plan_id == plan_id,
                TrainingPlanRow.user_id == user_id,
            )
            .order_by(PlannedSessionRow.scheduled_date.asc())
        )
        async with short_session(self._sessions) as session:
            rows = (await session.scalars(stmt)).all()
            return [session_from_row(row) for row in rows]


class SqlAlchemyAthleteStateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_latest(self, *, user_id: UUID) -> AthleteStateSnapshot | None:
        stmt = (
            select(AthleteStateSnapshotRow)
            .where(AthleteStateSnapshotRow.user_id == user_id)
            .order_by(AthleteStateSnapshotRow.version.desc())
            .limit(1)
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return athlete_state_from_row(row) if row else None
