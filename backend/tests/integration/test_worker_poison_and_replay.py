"""Poison Outbox 与显式 dead-letter replay 的真实 PostgreSQL 回归。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.contracts.durable_events import (
    TURN_FAILED_V1,
    TurnTerminalV1,
    new_turn_terminal_event,
)
from app.common.errors import ConflictError
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.outbox import EventConsumptionRow, OutboxEventRow
from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.outbox.writer import OutboxWriter
from app.workers.publisher import OutboxPublisher
from app.workers.replay import WorkerTaskReplayer
from app.workers.routing import FINALIZE_TERMINAL_TURN


class _Queue:
    def __init__(self) -> None:
        self.tasks = []

    async def enqueue(self, task, *, defer_by: timedelta | None = None) -> None:
        self.tasks.append(task)


@pytest.mark.asyncio
async def test_malformed_pending_outbox_is_quarantined_without_blocking_valid_row(
    sessions, user_id, clock
) -> None:
    event = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=user_id,
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    poison_id = new_id()
    async with sessions.begin() as session:
        OutboxWriter().add(session, event)
        session.add(
            OutboxEventRow(
                id=new_id(),
                event_id=poison_id,
                event_type=TURN_FAILED_V1,
                schema_version=0,
                aggregate_type="turn",
                aggregate_id=new_id(),
                user_id=user_id,
                occurred_at=clock.now(),
                payload={"invalid": True},
                correlation_id=new_id(),
                causation_id=None,
                trace_id=None,
                status="pending",
                available_at=clock.now(),
                claimed_by=None,
                claim_until=None,
                publish_attempt_count=0,
                last_error_code=None,
                created_at=clock.now() - timedelta(seconds=1),
                published_at=None,
                quarantined_at=None,
            )
        )
    queue = _Queue()
    result = await OutboxPublisher(
        repository=SqlAlchemyOutboxRepository(sessions),
        queue=queue,
        clock=clock,
        worker_id="poison-test",
    ).publish_batch()
    assert result.quarantined == 1
    assert result.published == 1
    async with sessions() as session:
        row = await session.scalar(select(OutboxEventRow).where(OutboxEventRow.event_id == poison_id))
        assert row.status == "quarantined"
    assert len(queue.tasks) == 1


@pytest.mark.asyncio
async def test_dead_letter_replay_requires_exact_route_and_preserves_event_identity(
    sessions, user_id, clock
) -> None:
    event = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=user_id,
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    async with sessions.begin() as session:
        OutboxWriter().add(session, event)
        session.add(
            EventConsumptionRow(
                consumer_name=FINALIZE_TERMINAL_TURN,
                consumer_version=1,
                event_id=event.event_id,
                user_id=user_id,
                status="dead_lettered",
                attempt_count=8,
                lease_owner=None,
                lease_until=None,
                last_error_code="cross_user_source",
                started_at=clock.now(),
                completed_at=clock.now(),
            )
        )
    queue = _Queue()
    replayer = WorkerTaskReplayer(
        outbox=SqlAlchemyOutboxRepository(sessions),
        receipts=SqlAlchemyConsumptionRepository(sessions),
        queue=queue,
        clock=clock,
    )
    with pytest.raises(ConflictError, match="worker_route_mismatch"): 
        await replayer.replay(
            event_id=event.event_id,
            consumer_name="project_episode",
            consumer_version=1,
        )
    result = await replayer.replay(
        event_id=event.event_id,
        consumer_name=FINALIZE_TERMINAL_TURN,
        consumer_version=1,
    )
    assert result.event_id == event.event_id
    assert queue.tasks[0].event.event_id == event.event_id
