from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.turn import TurnStatus
from app.common.clock import FrozenClock
from app.common.errors import ForbiddenError
from app.common.ids import new_id
from app.infrastructure.database.models.agent import MessageRow, TurnRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.repositories.conversation import SqlAlchemyConversationStore
from app.infrastructure.database.session import short_session


@pytest.mark.asyncio
async def test_start_and_commit_turn(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    clock: FrozenClock,
) -> None:
    store = SqlAlchemyConversationStore(sessions, clock)
    started = await store.start_turn(user_id=user_id, thread_id=None, content="hello")
    assert started.turn.status is TurnStatus.RUNNING
    assert started.user_message.content == "hello"
    committed = await store.commit_turn(
        user_id=user_id,
        turn_id=started.turn.id,
        assistant_content="hi",
    )
    assert committed.turn.status is TurnStatus.COMMITTED
    assert committed.assistant_message.content == "hi"
    assert committed.turn.assistant_message_id == committed.assistant_message.id


@pytest.mark.asyncio
async def test_fail_turn_keeps_user_message_without_assistant(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    clock: FrozenClock,
) -> None:
    store = SqlAlchemyConversationStore(sessions, clock)
    started = await store.start_turn(user_id=user_id, thread_id=None, content="oops")
    await store.fail_turn(user_id=user_id, turn_id=started.turn.id)

    async with short_session(sessions) as session:
        turn = await session.get(TurnRow, started.turn.id)
        assert turn is not None
        assert turn.status == TurnStatus.FAILED.value
        assert turn.assistant_message_id is None
        messages = (
            await session.scalars(select(MessageRow).where(MessageRow.turn_id == started.turn.id))
        ).all()
        assert [m.role for m in messages] == ["user"]


@pytest.mark.asyncio
async def test_cancel_turn(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    clock: FrozenClock,
) -> None:
    store = SqlAlchemyConversationStore(sessions, clock)
    started = await store.start_turn(user_id=user_id, thread_id=None, content="stop")
    await store.cancel_turn(user_id=user_id, turn_id=started.turn.id)
    async with short_session(sessions) as session:
        turn = await session.get(TurnRow, started.turn.id)
        assert turn is not None
        assert turn.status == TurnStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_thread_belongs_to_user(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    clock: FrozenClock,
) -> None:
    store = SqlAlchemyConversationStore(sessions, clock)
    started = await store.start_turn(user_id=user_id, thread_id=None, content="owner")
    other = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other, created_at=clock.now(), updated_at=clock.now()))
    with pytest.raises(ForbiddenError):
        await store.start_turn(
            user_id=other,
            thread_id=started.thread.id,
            content="forbidden",
        )
