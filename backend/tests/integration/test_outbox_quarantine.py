"""Poison durable schema 在 PostgreSQL 中持久隔离，不进入无限 retry。"""

from dataclasses import replace

import pytest
from sqlalchemy import select

from app.agent.contracts.durable_events import (
    TURN_FAILED_V1,
    TurnTerminalV1,
    new_turn_terminal_event,
)
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.outbox import OutboxEventRow
from app.infrastructure.outbox.repository import SqlAlchemyOutboxRepository
from app.infrastructure.outbox.writer import OutboxWriter
from app.workers.publisher import OutboxPublisher
from tests.durable import CollectingQueue


@pytest.mark.asyncio
async def test_unknown_schema_is_quarantined_without_queue_delivery(
    sessions,
    user_id,
    clock,
) -> None:
    valid = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=user_id,
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    poison = replace(valid, schema_version=99)
    async with sessions.begin() as session:
        OutboxWriter().add(session, poison)
    queue = CollectingQueue()
    result = await OutboxPublisher(
        repository=SqlAlchemyOutboxRepository(sessions),
        queue=queue,
        clock=clock,
        worker_id="quarantine-test",
    ).publish_batch()

    assert result.quarantined == 1
    assert queue.tasks == []
    async with sessions() as session:
        row = await session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.event_id == poison.event_id)
        )
    assert row is not None
    assert row.status == "quarantined"
    assert row.last_error_code == "unsupported_durable_event_schema"
    assert row.publish_attempt_count == 1
