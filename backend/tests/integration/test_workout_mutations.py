"""Workout / Feedback canonical mutation 与 Outbox 的真实事务验证。"""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.workout_command_service import (
    WorkoutCommandService,
    WorkoutFeedbackCommandService,
)
from app.coaching.contracts.durable_events import (
    WORKOUT_CHANGED_V1,
    WORKOUT_FEEDBACK_CHANGED_V1,
)
from app.coaching.domain.workout.models import WorkoutSource, WorkoutType
from app.coaching.ports.workout_mutation_store import (
    WorkoutFeedbackMutation,
    WorkoutMutation,
)
from app.common.clock import FrozenClock
from app.common.errors import NotFoundError
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import WorkoutFeedbackRow, WorkoutRow
from app.infrastructure.database.models.outbox import OutboxEventRow
from app.infrastructure.database.repositories.workout_mutation import (
    SqlAlchemyWorkoutMutationStore,
)
from app.infrastructure.database.session import short_session
from app.infrastructure.outbox.writer import OutboxWriter
from app.infrastructure.seed.vertical_slice import seed_vertical_slice


def _metadata() -> EventMetadata:
    return EventMetadata(correlation_id=new_id(), trace_id=new_id())


def _feedback_service(
    sessions: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> WorkoutFeedbackCommandService:
    return WorkoutFeedbackCommandService(
        SqlAlchemyWorkoutMutationStore(sessions, OutboxWriter()),
        clock,
    )


@pytest.mark.asyncio
async def test_feedback_record_and_update_write_versioned_outbox(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed = await seed_vertical_slice(session)
    service = _feedback_service(sessions, clock)
    feedback = await service.record(
        user_id=seed.user_id,
        workout_id=seed.workout_ids[0],
        mutation=WorkoutFeedbackMutation(
            perceived_exertion=5,
            subjective_fatigue=4,
            soreness=3,
            note="首次反馈",
        ),
        event_metadata=_metadata(),
    )
    updated = await service.update(
        user_id=seed.user_id,
        feedback_id=feedback.id,
        mutation=WorkoutFeedbackMutation(
            perceived_exertion=6,
            subjective_fatigue=5,
            soreness=4,
            note="修正反馈",
        ),
        event_metadata=_metadata(),
    )
    assert updated.created_at == feedback.created_at
    assert updated.updated_at == clock.now()

    async with short_session(sessions) as session:
        rows = (
            await session.scalars(
                select(OutboxEventRow)
                .where(
                    OutboxEventRow.event_type == WORKOUT_FEEDBACK_CHANGED_V1,
                    OutboxEventRow.aggregate_id == feedback.id,
                )
                .order_by(OutboxEventRow.created_at.asc(), OutboxEventRow.event_id.asc())
            )
        ).all()
    assert len(rows) == 2
    assert {row.payload["change_kind"] for row in rows} == {"recorded", "updated"}
    assert all(row.user_id == seed.user_id for row in rows)
    assert all(row.occurred_at == clock.now() for row in rows)


@pytest.mark.asyncio
async def test_feedback_record_revalidates_workout_owner(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    async with short_session(sessions, commit=True) as session:
        seed_a = await seed_vertical_slice(session)
        seed_b = await seed_vertical_slice(session)
    with pytest.raises(NotFoundError, match="workout_not_found"):
        await _feedback_service(sessions, clock).record(
            user_id=seed_b.user_id,
            workout_id=seed_a.workout_ids[0],
            mutation=WorkoutFeedbackMutation(
                perceived_exertion=5,
                subjective_fatigue=None,
                soreness=None,
                note=None,
            ),
            event_metadata=_metadata(),
        )


class _FailingOutboxWriter(OutboxWriter):
    def add(self, session: AsyncSession, event) -> None:
        raise RuntimeError("forced_outbox_failure")


@pytest.mark.asyncio
async def test_workout_row_rolls_back_when_outbox_write_fails(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    user_id: UUID,
) -> None:
    service = WorkoutCommandService(
        SqlAlchemyWorkoutMutationStore(sessions, _FailingOutboxWriter()),
        clock,
    )
    with pytest.raises(RuntimeError, match="forced_outbox_failure"):
        await service.record(
            user_id=user_id,
            mutation=WorkoutMutation(
                started_at=clock.now(),
                distance_m=5000,
                duration_s=1500,
                avg_heart_rate=140,
                max_heart_rate=160,
                workout_type=WorkoutType.EASY,
                source=WorkoutSource.MANUAL,
            ),
            event_metadata=_metadata(),
        )

    async with short_session(sessions) as session:
        workouts = (
            await session.scalars(select(WorkoutRow).where(WorkoutRow.user_id == user_id))
        ).all()
        feedback = (
            await session.scalars(
                select(WorkoutFeedbackRow).where(WorkoutFeedbackRow.user_id == user_id)
            )
        ).all()
        events = (
            await session.scalars(
                select(OutboxEventRow).where(
                    OutboxEventRow.user_id == user_id,
                    OutboxEventRow.event_type == WORKOUT_CHANGED_V1,
                )
            )
        ).all()
    assert workouts == []
    assert feedback == []
    assert events == []
