"""Workout / Feedback canonical mutation 与 Outbox 的同事务实现。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.contracts.durable_events import (
    ChangeKind,
    WorkoutChangedV1,
    WorkoutFeedbackChangedV1,
    new_workout_changed_event,
    new_workout_feedback_changed_event,
)
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.workout_mutation_store import (
    WorkoutFeedbackMutation,
    WorkoutMutation,
)
from app.common.errors import NotFoundError
from app.common.events import EventMetadata
from app.infrastructure.database.mappers import feedback_from_row, workout_from_row
from app.infrastructure.database.models.coaching import WorkoutFeedbackRow, WorkoutRow
from app.infrastructure.database.session import short_session
from app.infrastructure.outbox.writer import OutboxWriter


class SqlAlchemyWorkoutMutationStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
    ) -> None:
        self._sessions = sessions
        self._outbox = outbox

    async def record_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> Workout:
        async with short_session(self._sessions, commit=True) as session:
            row = WorkoutRow(
                id=workout_id,
                user_id=user_id,
                started_at=mutation.started_at,
                distance_m=mutation.distance_m,
                duration_s=mutation.duration_s,
                avg_heart_rate=mutation.avg_heart_rate,
                max_heart_rate=mutation.max_heart_rate,
                workout_type=mutation.workout_type.value,
                source=mutation.source.value,
                created_at=available_at,
                updated_at=available_at,
            )
            session.add(row)
            self._write_workout_event(
                session,
                row=row,
                change_kind=ChangeKind.RECORDED,
                available_at=available_at,
                event_metadata=event_metadata,
            )
            await session.flush()
            return workout_from_row(row)

    async def update_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> Workout:
        async with short_session(self._sessions, commit=True) as session:
            row = await session.scalar(
                select(WorkoutRow)
                .where(WorkoutRow.id == workout_id, WorkoutRow.user_id == user_id)
                .with_for_update()
            )
            if row is None:
                raise NotFoundError("workout_not_found")
            row.started_at = mutation.started_at
            row.distance_m = mutation.distance_m
            row.duration_s = mutation.duration_s
            row.avg_heart_rate = mutation.avg_heart_rate
            row.max_heart_rate = mutation.max_heart_rate
            row.workout_type = mutation.workout_type.value
            row.source = mutation.source.value
            row.updated_at = available_at
            self._write_workout_event(
                session,
                row=row,
                change_kind=ChangeKind.UPDATED,
                available_at=available_at,
                event_metadata=event_metadata,
            )
            await session.flush()
            return workout_from_row(row)

    async def record_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback:
        async with short_session(self._sessions, commit=True) as session:
            workout = await self._require_workout(
                session,
                user_id=user_id,
                workout_id=workout_id,
            )
            row = WorkoutFeedbackRow(
                id=feedback_id,
                user_id=user_id,
                workout_id=workout_id,
                perceived_exertion=mutation.perceived_exertion,
                subjective_fatigue=mutation.subjective_fatigue,
                soreness=mutation.soreness,
                note=mutation.note,
                created_at=available_at,
                updated_at=available_at,
            )
            session.add(row)
            self._write_feedback_event(
                session,
                row=row,
                source_fact_at=workout.started_at,
                change_kind=ChangeKind.RECORDED,
                available_at=available_at,
                event_metadata=event_metadata,
            )
            await session.flush()
            return feedback_from_row(row)

    async def update_feedback(
        self,
        *,
        user_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback:
        async with short_session(self._sessions, commit=True) as session:
            row = await session.scalar(
                select(WorkoutFeedbackRow)
                .where(
                    WorkoutFeedbackRow.id == feedback_id,
                    WorkoutFeedbackRow.user_id == user_id,
                )
                .with_for_update()
            )
            if row is None:
                raise NotFoundError("workout_feedback_not_found")
            workout = await self._require_workout(
                session,
                user_id=user_id,
                workout_id=row.workout_id,
            )
            row.perceived_exertion = mutation.perceived_exertion
            row.subjective_fatigue = mutation.subjective_fatigue
            row.soreness = mutation.soreness
            row.note = mutation.note
            row.updated_at = available_at
            self._write_feedback_event(
                session,
                row=row,
                source_fact_at=workout.started_at,
                change_kind=ChangeKind.UPDATED,
                available_at=available_at,
                event_metadata=event_metadata,
            )
            await session.flush()
            return feedback_from_row(row)

    async def _require_workout(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutRow:
        row = await session.scalar(
            select(WorkoutRow).where(
                WorkoutRow.id == workout_id,
                WorkoutRow.user_id == user_id,
            )
        )
        if row is None:
            raise NotFoundError("workout_not_found")
        return row

    def _write_workout_event(
        self,
        session: AsyncSession,
        *,
        row: WorkoutRow,
        change_kind: ChangeKind,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> None:
        self._outbox.add(
            session,
            new_workout_changed_event(
                user_id=row.user_id,
                payload=WorkoutChangedV1(
                    workout_id=row.id,
                    change_kind=change_kind,
                    source_fact_at=row.started_at,
                    available_at=available_at,
                ),
                metadata=event_metadata,
            ),
        )

    def _write_feedback_event(
        self,
        session: AsyncSession,
        *,
        row: WorkoutFeedbackRow,
        source_fact_at: datetime,
        change_kind: ChangeKind,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> None:
        self._outbox.add(
            session,
            new_workout_feedback_changed_event(
                user_id=row.user_id,
                payload=WorkoutFeedbackChangedV1(
                    feedback_id=row.id,
                    workout_id=row.workout_id,
                    change_kind=change_kind,
                    source_fact_at=source_fact_at,
                    available_at=available_at,
                ),
                metadata=event_metadata,
            ),
        )
