from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.plan.models import PlanChange, PlanChangeStatus


class PlanChangeRepository(Protocol):
    async def get(self, *, user_id: UUID, plan_change_id: UUID) -> PlanChange | None:
        ...

    async def get_unresolved(self, *, user_id: UUID) -> PlanChange | None:
        ...

    async def list_by_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
    ) -> list[PlanChange]:
        ...

    async def add(self, plan_change: PlanChange) -> PlanChange:
        ...

    async def update_status(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        status: PlanChangeStatus,
        resolved_at: datetime | None = None,
        resulting_plan_id: UUID | None = None,
    ) -> PlanChange:
        ...
