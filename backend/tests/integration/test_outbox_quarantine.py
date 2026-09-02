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
    """验证：未知 schema_version 的事件被直接隔离——不投递队列、不进入无限重试，错误码落库。"""
    valid = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=user_id,
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    # replace：dataclass 拷贝工具，这里用它伪造一个未来 schema 版本的毒事件。
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
    # 队列必须零投递：隔离发生在 publisher 边界，毒事件不出本地消息表。
    assert queue.tasks == []
    async with sessions() as session:
        row = await session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.event_id == poison.event_id)
        )
    assert row is not None
    assert row.status == "quarantined"
    assert row.last_error_code == "unsupported_durable_event_schema"
    assert row.publish_attempt_count == 1
