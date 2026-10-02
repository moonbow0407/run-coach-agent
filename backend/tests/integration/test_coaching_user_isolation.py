"""训练台查询的数据隔离：课次与目标均按 user_id 严格隔离，杜绝跨用户泄漏。"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.workout_service import WorkoutQueryService
from app.common.clock import FrozenClock
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import TrainingGoalRow, WorkoutRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.repositories.coaching import (
    SqlAlchemyGoalRepository,
    SqlAlchemyWorkoutRepository,
)
from app.infrastructure.database.session import short_session


async def _user(sessions: async_sessionmaker[AsyncSession], now: datetime) -> UUID:
    """新建一个最小用户行并返回其 id，用于构造两个互不相干的用户。"""
    uid = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=uid, created_at=now, updated_at=now))
    return uid


@pytest.mark.asyncio
async def test_workouts_are_isolated_by_user(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """验证：近期课次查询按 user_id 过滤，A/B 两个用户各自只看到自己的那节课。"""
    now = clock.now()
    user_a = await _user(sessions, now)
    user_b = await _user(sessions, now)
    # 分别给 A、B 各写一节课，内容可区分。
    async with short_session(sessions, commit=True) as session:
        session.add(
            WorkoutRow(
                id=new_id(),
                user_id=user_a,
                started_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
                distance_m=8000,
                duration_s=2400,
                avg_heart_rate=140,
                max_heart_rate=160,
                workout_type="easy",
                source="manual",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            WorkoutRow(
                id=new_id(),
                user_id=user_b,
                started_at=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
                distance_m=10000,
                duration_s=3000,
                avg_heart_rate=150,
                max_heart_rate=170,
                workout_type="tempo",
                source="manual",
                created_at=now,
                updated_at=now,
            )
        )

    service = WorkoutQueryService(SqlAlchemyWorkoutRepository(sessions), clock)
    a_workouts = await service.get_recent_workouts(user_id=user_a, days=30)
    b_workouts = await service.get_recent_workouts(user_id=user_b, days=30)
    assert {w.user_id for w in a_workouts} == {user_a}
    assert {w.user_id for w in b_workouts} == {user_b}
    assert len(a_workouts) == 1
    assert len(b_workouts) == 1


@pytest.mark.asyncio
async def test_active_goal_missing_returns_none(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
) -> None:
    """验证：没有目标的用户查询活跃目标返回 None，而不是报错或返回他人数据。"""
    service = GoalQueryService(SqlAlchemyGoalRepository(sessions))
    assert await service.get_active_goal(user_id=user_id) is None


@pytest.mark.asyncio
async def test_active_goal_does_not_leak_across_users(
    sessions: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """验证：A 的活跃目标对 B 不可见——B 查询结果为 None，无跨用户泄漏。"""
    now = clock.now()
    user_a = await _user(sessions, now)
    user_b = await _user(sessions, now)
    async with short_session(sessions, commit=True) as session:
        session.add(
            TrainingGoalRow(
                id=new_id(),
                user_id=user_a,
                goal_type="race",
                race_date=None,
                race_distance_m=21097,
                target_time_s=6600,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    service = GoalQueryService(SqlAlchemyGoalRepository(sessions))
    assert await service.get_active_goal(user_id=user_a) is not None
    assert await service.get_active_goal(user_id=user_b) is None
