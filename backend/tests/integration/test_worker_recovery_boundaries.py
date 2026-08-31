"""恢复扫描与 durable task 边界回归。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.contracts.durable_events import (
    TURN_FAILED_V1,
    TurnTerminalV1,
    new_turn_terminal_event,
)
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.outbox import EventConsumptionRow, OutboxEventRow
from app.infrastructure.outbox.repository import SqlAlchemyOutboxRepository
from app.infrastructure.outbox.writer import OutboxWriter
from app.workers.recovery import OutboxRecoveryScanner
from app.workers.routing import FINALIZE_TERMINAL_TURN


class _Queue:
    def __init__(self) -> None:
        self.tasks = []

    async def enqueue(self, task, *, defer_by=None) -> None:
        self.tasks.append(task)


@pytest.mark.asyncio
async def test_recovery_batch_does_not_starve_newer_event_with_terminal_history(
    sessions, user_id, clock
) -> None:
    older = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=user_id,
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    newer = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=user_id,
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    async with sessions.begin() as session:
        OutboxWriter().add(session, older)
        OutboxWriter().add(session, newer)
    async with sessions.begin() as session:
        for event in (older, newer):
            row = await session.scalar(
                select(OutboxEventRow).where(
                    OutboxEventRow.event_id == event.event_id
                )
            )
            row.status = "published"
            row.published_at = clock.now()
        session.add(
            EventConsumptionRow(
                consumer_name=FINALIZE_TERMINAL_TURN,
                consumer_version=1,
                event_id=older.event_id,
                user_id=user_id,
                status="completed",
                attempt_count=1,
                lease_owner=None,
                lease_until=None,
                last_error_code=None,
                started_at=clock.now(),
                completed_at=clock.now(),
            )
        )
    queue = _Queue()
    result = await OutboxRecoveryScanner(
        outbox=SqlAlchemyOutboxRepository(sessions),
        queue=queue,
        clock=clock,
        safety_window=timedelta(0),
        batch_size=1,
    ).scan()
    assert result.tasks_reenqueued == 1
    assert queue.tasks[0].event.event_id == newer.event_id
