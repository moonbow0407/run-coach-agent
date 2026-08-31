"""coaching 仓储：各领域事实的 SQL 查询实现。

只做取数与 Row -> 领域对象映射，不含业务规则；
所有查询都强制携带 user_id 条件，这是用户数据隔离的最后一道防线。
快照追加与计划激活只负责事务、行锁和持久化，不决定疲劳或调整规则。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.goal.models import GoalStatus, TrainingGoal
from app.coaching.domain.plan.models import (
    PlanChange,
    PlanChangeStatus,
    PlannedSession,
    PlanStatus,
    TrainingPlan,
)
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.common.errors import ConflictError, NotFoundError
from app.infrastructure.database.locking import lock_user_row
from app.infrastructure.database.mappers import (
    athlete_state_from_row,
    feedback_from_row,
    goal_from_row,
    payload_to_json,
    plan_change_from_row,
    plan_from_row,
    session_from_row,
    workout_from_row,
)
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlanChangeRow,
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

    async def list_between(
        self,
        *,
        user_id: UUID,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[Workout]:
        stmt: Select[tuple[WorkoutRow]] = (
            select(WorkoutRow)
            .where(
                WorkoutRow.user_id == user_id,
                WorkoutRow.started_at >= start,
                WorkoutRow.started_at <= end,
            )
            .order_by(WorkoutRow.started_at.asc())
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

    async def list_feedback_for_workouts(
        self,
        *,
        user_id: UUID,
        workout_ids: list[UUID],
        end: datetime,
    ) -> list[WorkoutFeedback]:
        if not workout_ids:
            return []
        stmt = (
            select(WorkoutFeedbackRow)
            .where(
                WorkoutFeedbackRow.user_id == user_id,
                WorkoutFeedbackRow.workout_id.in_(workout_ids),
                # 证据时间上界：as_of 之后创建的反馈不允许进入状态计算。
                WorkoutFeedbackRow.created_at <= end,
            )
            # 固定排序让"同一 workout 多条反馈取最新"成为确定性规则。
            .order_by(WorkoutFeedbackRow.created_at.asc(), WorkoutFeedbackRow.id.asc())
        )
        async with short_session(self._sessions) as session:
            rows = (await session.scalars(stmt)).all()
            return [feedback_from_row(row) for row in rows]


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

    async def get(self, *, user_id: UUID, plan_id: UUID) -> TrainingPlan | None:
        stmt = select(TrainingPlanRow).where(
            TrainingPlanRow.id == plan_id,
            TrainingPlanRow.user_id == user_id,
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


_UNRESOLVED_STATUSES = (
    PlanChangeStatus.DRAFT.value,
    PlanChangeStatus.PENDING_CONFIRMATION.value,
)


class SqlAlchemyPlanChangeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, *, user_id: UUID, plan_change_id: UUID) -> PlanChange | None:
        stmt = select(PlanChangeRow).where(
            PlanChangeRow.id == plan_change_id,
            PlanChangeRow.user_id == user_id,
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return plan_change_from_row(row) if row else None

    async def get_unresolved(self, *, user_id: UUID) -> PlanChange | None:
        stmt = (
            select(PlanChangeRow)
            .where(
                PlanChangeRow.user_id == user_id,
                PlanChangeRow.status.in_(_UNRESOLVED_STATUSES),
            )
            .order_by(PlanChangeRow.created_at.desc())
            .limit(1)
        )
        async with short_session(self._sessions) as session:
            row = await session.scalar(stmt)
            return plan_change_from_row(row) if row else None

    async def list_by_turn(self, *, user_id: UUID, turn_id: UUID) -> list[PlanChange]:
        stmt = (
            select(PlanChangeRow)
            .where(
                PlanChangeRow.user_id == user_id,
                PlanChangeRow.source_turn_id == turn_id,
            )
            .order_by(PlanChangeRow.created_at.asc())
        )
        async with short_session(self._sessions) as session:
            rows = (await session.scalars(stmt)).all()
            return [plan_change_from_row(row) for row in rows]

    async def add(self, plan_change: PlanChange) -> PlanChange:
        row = PlanChangeRow(
            id=plan_change.id,
            user_id=plan_change.user_id,
            from_plan_id=plan_change.from_plan_id,
            from_plan_version=plan_change.from_plan_version,
            based_on_state_id=plan_change.based_on_state_id,
            based_on_state_version=plan_change.based_on_state_version,
            source_turn_id=plan_change.source_turn_id,
            source_run_id=plan_change.source_run_id,
            as_of=plan_change.as_of,
            change_type=plan_change.change_type.value,
            payload=payload_to_json(plan_change.payload),
            reason=plan_change.reason,
            status=plan_change.status.value,
            created_at=plan_change.created_at,
            resolved_at=plan_change.resolved_at,
            resulting_plan_id=plan_change.resulting_plan_id,
        )
        try:
            async with short_session(self._sessions, commit=True) as session:
                session.add(row)
                await session.flush()
                return plan_change_from_row(row)
        except IntegrityError as exc:
            raise ConflictError("unresolved_plan_change_exists") from exc

    async def transition(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        expected: PlanChangeStatus,
        target: PlanChangeStatus,
        resolved_at: datetime | None = None,
        resulting_plan_id: UUID | None = None,
    ) -> PlanChange:
        """用户行锁 + CAS：防止 stale read 后的 last-write-wins 覆盖。"""
        async with short_session(self._sessions, commit=True) as session:
            await lock_user_row(session, user_id)
            row = await session.scalar(
                select(PlanChangeRow).where(
                    PlanChangeRow.id == plan_change_id,
                    PlanChangeRow.user_id == user_id,
                )
            )
            if row is None:
                raise NotFoundError("计划调整不存在")
            if PlanChangeStatus(row.status) is not expected:
                raise ConflictError("plan_change_status_conflict")
            row.status = target.value
            if resolved_at is not None:
                row.resolved_at = resolved_at
            if resulting_plan_id is not None:
                row.resulting_plan_id = resulting_plan_id
            await session.flush()
            return plan_change_from_row(row)
