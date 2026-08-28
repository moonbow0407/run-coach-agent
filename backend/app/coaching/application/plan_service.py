"""训练计划查询服务。"""

from uuid import UUID

from app.coaching.domain.plan.models import ActivePlan
from app.coaching.ports.plan_repository import PlanRepository


class PlanQueryService:
    """读取用户当前生效的计划及其全部课次（两次查询组合成 ActivePlan）。"""

    def __init__(self, repository: PlanRepository) -> None:
        self._repository = repository

    async def get_active_plan(self, *, user_id: UUID) -> ActivePlan | None:
        plan = await self._repository.get_active(user_id=user_id)
        if plan is None:
            return None
        sessions = await self._repository.list_sessions(user_id=user_id, plan_id=plan.id)
        return ActivePlan(plan=plan, sessions=tuple(sessions))
