"""Athlete State evidence read、评估提交与 Outbox 的单用户锁事务。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.contracts.durable_events import (
    AthleteStateRecomputedV1,
    new_athlete_state_recomputed_event,
)
from app.coaching.domain.athlete.evaluator import AthleteStateAssessment
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_recompute_uow import (
    AthleteStateEvidenceSet,
    AthleteStateRecomputeTransaction,
)
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.locking import lock_user_row
from app.infrastructure.database.mappers import (
    athlete_state_from_row,
    feedback_from_row,
    signals_to_json,
    workout_from_row,
)
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.outbox.writer import OutboxWriter

_EVIDENCE_LOOKBACK = timedelta(days=14)


class SqlAlchemyAthleteStateRecomputeUnitOfWork:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
    ) -> None:
        self._sessions = sessions
        self._outbox = outbox

    @asynccontextmanager
    async def transaction(
        self,
        *,
        user_id: UUID,
    ) -> AsyncIterator[AthleteStateRecomputeTransaction]:
        async with self._sessions() as session:
            try:
                await lock_user_row(session, user_id)
                yield _SqlAlchemyAthleteStateRecomputeTransaction(
                    session=session,
                    outbox=self._outbox,
                    user_id=user_id,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise


class _SqlAlchemyAthleteStateRecomputeTransaction:
    def __init__(
        self,
        *,
        session: AsyncSession,
        outbox: OutboxWriter,
        user_id: UUID,
    ) -> None:
        self._session = session
        self._outbox = outbox
        self._user_id = user_id

    async def load_evidence(
        self,
        *,
        trigger_available_at: datetime,
        observed_at: datetime,
    ) -> AthleteStateEvidenceSet:
        latest_row = await self._session.scalar(
            select(AthleteStateSnapshotRow)
            .where(AthleteStateSnapshotRow.user_id == self._user_id)
            .order_by(AthleteStateSnapshotRow.version.desc())
            .limit(1)
        )
        workout_cutoff = await self._session.scalar(
            select(func.max(WorkoutRow.updated_at)).where(
                WorkoutRow.user_id == self._user_id,
                WorkoutRow.updated_at <= observed_at,
            )
        )
        feedback_cutoff = await self._session.scalar(
            select(func.max(WorkoutFeedbackRow.updated_at)).where(
                WorkoutFeedbackRow.user_id == self._user_id,
                WorkoutFeedbackRow.updated_at <= observed_at,
            )
        )
        cutoff = max(
            moment
            for moment in (trigger_available_at, workout_cutoff, feedback_cutoff)
            if moment is not None
        )
        start = cutoff - _EVIDENCE_LOOKBACK
        workout_rows = (
            await self._session.scalars(
                select(WorkoutRow)
                .where(
                    WorkoutRow.user_id == self._user_id,
                    WorkoutRow.updated_at <= observed_at,
                    WorkoutRow.started_at >= start,
                    WorkoutRow.started_at <= cutoff,
                )
                .order_by(WorkoutRow.started_at.asc(), WorkoutRow.id.asc())
            )
        ).all()
        workout_ids = [row.id for row in workout_rows]
        feedback_rows: tuple[WorkoutFeedbackRow, ...] = ()
        if workout_ids:
            feedback_rows = tuple(
                (
                    await self._session.scalars(
                        select(WorkoutFeedbackRow)
                        .where(
                            WorkoutFeedbackRow.user_id == self._user_id,
                            WorkoutFeedbackRow.workout_id.in_(workout_ids),
                            WorkoutFeedbackRow.updated_at <= cutoff,
                        )
                        .order_by(
                            WorkoutFeedbackRow.created_at.asc(),
                            WorkoutFeedbackRow.id.asc(),
                        )
                    )
                ).all()
            )
        return AthleteStateEvidenceSet(
            latest_snapshot=(
                athlete_state_from_row(latest_row) if latest_row is not None else None
            ),
            workouts=tuple(workout_from_row(row) for row in workout_rows),
            feedback=tuple(feedback_from_row(row) for row in feedback_rows),
            cutoff=cutoff,
        )

    async def append_snapshot(
        self,
        *,
        as_of: datetime,
        assessment: AthleteStateAssessment,
        created_at: datetime,
        event_metadata: EventMetadata,
    ) -> AthleteStateSnapshot:
        latest_version = await self._session.scalar(
            select(func.max(AthleteStateSnapshotRow.version)).where(
                AthleteStateSnapshotRow.user_id == self._user_id
            )
        )
        row = AthleteStateSnapshotRow(
            id=new_id(),
            user_id=self._user_id,
            version=(latest_version or 0) + 1,
            as_of=as_of,
            fatigue_level=(
                assessment.fatigue_level.value if assessment.fatigue_level else None
            ),
            recovery_level=(
                assessment.recovery_level.value if assessment.recovery_level else None
            ),
            recent_training_load=assessment.recent_training_load,
            workout_completion_rate=assessment.workout_completion_rate,
            training_load_coverage=assessment.training_load_coverage,
            signals=signals_to_json(assessment.signals),
            confidence=assessment.confidence,
            algorithm_version=assessment.algorithm_version,
            created_at=created_at,
        )
        self._session.add(row)
        self._outbox.add(
            self._session,
            new_athlete_state_recomputed_event(
                user_id=self._user_id,
                payload=AthleteStateRecomputedV1(
                    snapshot_id=row.id,
                    snapshot_version=row.version,
                    as_of=as_of,
                    algorithm_version=assessment.algorithm_version,
                ),
                metadata=event_metadata,
            ),
        )
        await self._session.flush()
        return athlete_state_from_row(row)
