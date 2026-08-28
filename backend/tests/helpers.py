from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.lifecycle.events import LifecycleEvent
from app.common.clock import Clock
from app.common.ids import new_id
from app.identity.application.request_context import RequestContext
from app.infrastructure.database.models.agent import MessageRow, RunStepRow, TurnRow
from app.infrastructure.database.session import short_session


def record_events(dispatcher: LifecycleDispatcher) -> list[LifecycleEvent]:
    events: list[LifecycleEvent] = []

    def listener(event: LifecycleEvent) -> None:
        events.append(event)

    dispatcher.subscribe(listener)
    return events


def request_context_for(user_id: UUID, clock: Clock) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        request_id=new_id(),
        trace_id=new_id(),
        timestamp=clock.now(),
    )


def event_types(events: list[LifecycleEvent]) -> list[str]:
    return [type(event).__name__ for event in events]


async def load_turn(
    sessions: async_sessionmaker[AsyncSession],
    turn_id: UUID,
) -> TurnRow:
    async with short_session(sessions) as session:
        row = await session.get(TurnRow, turn_id)
        assert row is not None
        return row


async def load_turn_messages(
    sessions: async_sessionmaker[AsyncSession],
    turn_id: UUID,
) -> list[MessageRow]:
    async with short_session(sessions) as session:
        rows = (
            await session.scalars(
                select(MessageRow)
                .where(MessageRow.turn_id == turn_id)
                .order_by(MessageRow.created_at.asc())
            )
        ).all()
        return list(rows)


async def load_run_steps(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
) -> list[RunStepRow]:
    async with short_session(sessions) as session:
        rows = (
            await session.scalars(
                select(RunStepRow)
                .where(RunStepRow.run_id == run_id)
                .order_by(RunStepRow.index.asc())
            )
        ).all()
        return list(rows)


def find_event(events: list[LifecycleEvent], type_name: str) -> LifecycleEvent | None:
    for event in events:
        if type(event).__name__ == type_name:
            return event
    return None
