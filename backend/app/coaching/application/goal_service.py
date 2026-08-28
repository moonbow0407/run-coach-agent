from uuid import UUID

from app.coaching.domain.goal.models import TrainingGoal
from app.coaching.ports.goal_repository import GoalRepository


class GoalQueryService:
    def __init__(self, repository: GoalRepository) -> None:
        self._repository = repository

    async def get_active_goal(self, *, user_id: UUID) -> TrainingGoal | None:
        return await self._repository.get_active(user_id=user_id)
