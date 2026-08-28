from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.agent.ports.capability_executor import CapabilityExecutionContext
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.workout_service import WorkoutQueryService
from app.common.clock import FrozenClock
from app.common.errors import CapabilityError
from app.common.ids import new_id
from app.infrastructure.capabilities.simple_executor import SimpleCapabilityExecutor
from app.infrastructure.database.models.coaching import WorkoutRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.repositories.coaching import (
    SqlAlchemyAthleteStateRepository,
    SqlAlchemyGoalRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyWorkoutRepository,
)
from app.infrastructure.database.session import short_session


def _executor(sessions, clock: FrozenClock) -> SimpleCapabilityExecutor:
    return SimpleCapabilityExecutor(
        WorkoutQueryService(SqlAlchemyWorkoutRepository(sessions), clock),
        GoalQueryService(SqlAlchemyGoalRepository(sessions)),
        PlanQueryService(SqlAlchemyPlanRepository(sessions)),
        AthleteStateQueryService(SqlAlchemyAthleteStateRepository(sessions)),
    )


@pytest.mark.asyncio
async def test_capability_uses_trusted_user_id_not_arguments(
    sessions,
    clock: FrozenClock,
) -> None:
    now = clock.now()
    user_a = new_id()
    user_b = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=user_a, created_at=now, updated_at=now))
        session.add(UserRow(id=user_b, created_at=now, updated_at=now))
        await session.flush()
        session.add(
            WorkoutRow(
                id=new_id(),
                user_id=user_a,
                started_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
                distance_m=8000,
                duration_s=2400,
                avg_heart_rate=140,
                max_heart_rate=150,
                workout_type="easy",
                source="manual",
                created_at=now,
            )
        )
        session.add(
            WorkoutRow(
                id=new_id(),
                user_id=user_b,
                started_at=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
                distance_m=16000,
                duration_s=4800,
                avg_heart_rate=150,
                max_heart_rate=170,
                workout_type="long_run",
                source="manual",
                created_at=now,
            )
        )

    executor = _executor(sessions, clock)
    context = CapabilityExecutionContext(
        user_id=user_a,
        run_id=new_id(),
        turn_id=new_id(),
        request_id=new_id(),
        timestamp=now,
    )
    observation = await executor.execute(
        name="get_recent_workouts",
        arguments={"days": 30},
        context=context,
    )
    assert observation.status == "success"
    assert isinstance(observation.data, list)
    assert len(observation.data) == 1
    assert observation.data[0]["user_id"] == str(user_a)
    assert observation.data[0]["distance_m"] == 8000


@pytest.mark.asyncio
async def test_capability_rejects_identity_in_arguments(
    sessions,
    clock: FrozenClock,
    user_id: UUID,
) -> None:
    executor = _executor(sessions, clock)
    context = CapabilityExecutionContext(
        user_id=user_id,
        run_id=new_id(),
        turn_id=new_id(),
        request_id=new_id(),
        timestamp=clock.now(),
    )
    with pytest.raises(CapabilityError, match="身份字段"):
        await executor.execute(
            name="get_recent_workouts",
            arguments={"days": 14, "user_id": str(new_id())},
            context=context,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [None, True, 0, 366, "14"])
async def test_capability_returns_error_observation_for_invalid_days(
    sessions,
    clock: FrozenClock,
    user_id: UUID,
    days,
) -> None:
    executor = _executor(sessions, clock)
    context = CapabilityExecutionContext(
        user_id=user_id,
        run_id=new_id(),
        turn_id=new_id(),
        request_id=new_id(),
        timestamp=clock.now(),
    )

    observation = await executor.execute(
        name="get_recent_workouts",
        arguments={"days": days},
        context=context,
    )

    assert observation.status == "error"
    assert observation.error is not None
