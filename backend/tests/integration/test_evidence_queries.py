"""Evidence 查询：as_of 上界与批量 Feedback，禁止用未来训练计算过去状态。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import FrozenClock
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import WorkoutFeedbackRow, WorkoutRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.repositories.coaching import SqlAlchemyWorkoutRepository
from app.infrastructure.database.session import short_session

AS_OF = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


async def _user(sessions: async_sessionmaker[AsyncSession], now: datetime) -> UUID:
    uid = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=uid, created_at=now, updated_at=now))
    return uid


@pytest.mark.asyncio
async def test_list_between_excludes_future_and_respects_start(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    user_id = await _user(sessions, clock.now())
    past = new_id()
    future = new_id()
    too_old = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(
            WorkoutRow(
                id=too_old,
                user_id=user_id,
                started_at=AS_OF - timedelta(days=20),
                distance_m=1000,
                duration_s=600,
                avg_heart_rate=120,
                max_heart_rate=130,
                workout_type="easy",
                source="manual",
                created_at=clock.now(),
            )
        )
        session.add(
            WorkoutRow(
                id=past,
                user_id=user_id,
                started_at=AS_OF - timedelta(days=1),
                distance_m=8000,
                duration_s=2400,
                avg_heart_rate=140,
                max_heart_rate=160,
                workout_type="easy",
                source="manual",
                created_at=clock.now(),
            )
        )
        session.add(
            WorkoutRow(
                id=future,
                user_id=user_id,
                started_at=AS_OF + timedelta(hours=3),
                distance_m=8000,
                duration_s=2400,
                avg_heart_rate=140,
                max_heart_rate=160,
                workout_type="tempo",
                source="manual",
                created_at=clock.now(),
            )
        )
    repo = SqlAlchemyWorkoutRepository(sessions)
    found = await repo.list_between(
        user_id=user_id,
        start=AS_OF - timedelta(days=7),
        end=AS_OF,
        limit=50,
    )
    ids = {item.id for item in found}
    assert past in ids
    assert future not in ids
    assert too_old not in ids
    assert all(item.started_at <= AS_OF for item in found)
    assert all(item.started_at >= AS_OF - timedelta(days=7) for item in found)


@pytest.mark.asyncio
async def test_list_feedback_for_workouts_is_batched(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    user_id = await _user(sessions, clock.now())
    workout_ids = [new_id(), new_id(), new_id()]
    async with short_session(sessions, commit=True) as session:
        for index, workout_id in enumerate(workout_ids):
            session.add(
                WorkoutRow(
                    id=workout_id,
                    user_id=user_id,
                    started_at=AS_OF - timedelta(days=index + 1),
                    distance_m=5000,
                    duration_s=1500,
                    avg_heart_rate=140,
                    max_heart_rate=150,
                    workout_type="easy",
                    source="manual",
                    created_at=clock.now(),
                )
            )
        await session.flush()
        for workout_id in workout_ids:
            session.add(
                WorkoutFeedbackRow(
                    id=new_id(),
                    user_id=user_id,
                    workout_id=workout_id,
                    perceived_exertion=5,
                    subjective_fatigue=4,
                    soreness=4,
                    note=None,
                    created_at=clock.now(),
                )
            )
    repo = SqlAlchemyWorkoutRepository(sessions)
    feedbacks = await repo.list_feedback_for_workouts(
        user_id=user_id, workout_ids=workout_ids
    )
    assert len(feedbacks) == 3
    assert {item.workout_id for item in feedbacks} == set(workout_ids)


@pytest.mark.asyncio
async def test_list_between_is_user_isolated(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    user_a = await _user(sessions, clock.now())
    user_b = await _user(sessions, clock.now())
    async with short_session(sessions, commit=True) as session:
        session.add(
            WorkoutRow(
                id=new_id(),
                user_id=user_a,
                started_at=AS_OF - timedelta(days=1),
                distance_m=8000,
                duration_s=2400,
                avg_heart_rate=140,
                max_heart_rate=160,
                workout_type="easy",
                source="manual",
                created_at=clock.now(),
            )
        )
        session.add(
            WorkoutRow(
                id=new_id(),
                user_id=user_b,
                started_at=AS_OF - timedelta(days=1),
                distance_m=10000,
                duration_s=3000,
                avg_heart_rate=150,
                max_heart_rate=170,
                workout_type="tempo",
                source="manual",
                created_at=clock.now(),
            )
        )
    repo = SqlAlchemyWorkoutRepository(sessions)
    a_rows = await repo.list_between(
        user_id=user_a, start=AS_OF - timedelta(days=7), end=AS_OF, limit=50
    )
    assert len(a_rows) == 1
    assert a_rows[0].user_id == user_a
