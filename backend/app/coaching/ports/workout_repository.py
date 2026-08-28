from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback


class WorkoutRepository(Protocol):
    async def list_recent(
        self,
        *,
        user_id: UUID,
        since: datetime,
        limit: int,
    ) -> list[Workout]:
        ...

    async def get(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> Workout | None:
        ...

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        ...
