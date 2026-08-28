from typing import Protocol
from uuid import UUID

from app.coaching.domain.goal.models import TrainingGoal


class GoalRepository(Protocol):
    async def get_active(self, *, user_id: UUID) -> TrainingGoal | None:
        ...
