"""非法 durable enum 必须在 Publisher 边界进入 quarantine。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.coaching.contracts.durable_events import (
    ChangeKind,
    WorkoutChangedV1,
    new_workout_changed_event,
)
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.outbox import OutboxEventRow
from app.infrastructure.outbox.repository import SqlAlchemyOutboxRepository
from app.infrastructure.outbox.writer import OutboxWriter
from app.workers.publisher import OutboxPublisher


class _Queue:
    async def enqueue(self, task, *, defer_by: timedelta | None = None) -> None:
        raise AssertionError("poison event must not be enqueued")


@pytest.mark.asyncio
async def test_invalid_change_kind_is_quarantined(sessions, user_id, clock) -> None:
    event = new_workout_changed_event(
        user_id=user_id,
        payload=WorkoutChangedV1(new_id(), ChangeKind.RECORDED, clock.now(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    async with sessions.begin() as session:
        OutboxWriter().add(session, event)
    async with sessions.begin() as session:
        row = await session.scalar(select(OutboxEventRow).where(OutboxEventRow.event_id == event.event_id))
        payload = dict(row.payload)
        payload["change_kind"] = "bogus"
        row.payload = payload
    result = await OutboxPublisher(
        repository=SqlAlchemyOutboxRepository(sessions),
        queue=_Queue(),
        clock=clock,
        worker_id="invalid-enum-test",
    ).publish_batch()
    assert result.quarantined == 1
    async with sessions() as session:
        row = await session.scalar(select(OutboxEventRow).where(OutboxEventRow.event_id == event.event_id))
        assert row.status == "quarantined"
