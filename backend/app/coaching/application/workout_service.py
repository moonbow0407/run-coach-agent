from datetime import timedelta
from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.workout_repository import WorkoutRepository
from app.common.clock import Clock
from app.common.errors import DomainError


class WorkoutQueryService:
    def __init__(self, repository: WorkoutRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def get_recent_workouts(self, *, user_id: UUID, days: int) -> list[Workout]:
        if days <= 0:
            raise DomainError("days 必须为正整数")
        since = self._clock.now() - timedelta(days=days)
        return await self._repository.list_recent(user_id=user_id, since=since, limit=50)

    async def get_workout(self, *, user_id: UUID, workout_id: UUID) -> Workout | None:
        return await self._repository.get(user_id=user_id, workout_id=workout_id)

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        return await self._repository.get_feedback(user_id=user_id, workout_id=workout_id)
