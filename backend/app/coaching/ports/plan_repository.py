from typing import Protocol
from uuid import UUID

from app.coaching.domain.plan.models import PlannedSession, TrainingPlan


class PlanRepository(Protocol):
    async def get_active(self, *, user_id: UUID) -> TrainingPlan | None:
        ...

    async def get(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> TrainingPlan | None:
        ...

    async def list_sessions(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> list[PlannedSession]:
        ...
