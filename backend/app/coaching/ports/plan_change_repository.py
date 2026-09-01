from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.plan.models import PlanChange, PlanChangeStatus


class PlanChangeRepository(Protocol):
    async def get(self, *, user_id: UUID, plan_change_id: UUID) -> PlanChange | None:
        ...

    async def get_unresolved(self, *, user_id: UUID) -> PlanChange | None:
        ...

    async def get_pending(self, *, user_id: UUID) -> PlanChange | None:
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

    async def transition(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        expected: PlanChangeStatus,
        target: PlanChangeStatus,
        resolved_at: datetime | None = None,
        resulting_plan_id: UUID | None = None,
    ) -> PlanChange:
        """CAS 状态转换：在用户行锁下仅当当前状态 == expected 才写入 target。

        拒绝 stale read + last-write-wins；当前状态不符时抛 ConflictError，
        由调用方决定幂等返回还是上报冲突。confirm 的 CONFIRMED 写入属于
        PlanActivationStore 的原子激活事务，不走本方法。
        """
        ...
