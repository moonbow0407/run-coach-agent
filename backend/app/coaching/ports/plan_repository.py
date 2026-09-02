"""训练计划仓储端口：读取 Plan 与 PlannedSession 的抽象。"""

from typing import Protocol  # Protocol：结构化鸭子类型，只约束方法签名，不要求继承
from uuid import UUID

from app.coaching.domain.plan.models import PlannedSession, TrainingPlan


class PlanRepository(Protocol):
    """训练计划只读仓储；实现方负责 user_id 隔离与状态过滤。"""

    async def get_active(self, *, user_id: UUID) -> TrainingPlan | None:
        """读取用户当前生效（ACTIVE）版本的计划；没有则返回 None。"""
        ...

    async def get(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> TrainingPlan | None:
        """按 id 读取指定计划（不限 ACTIVE），不存在或不属于该用户返回 None。"""
        ...

    async def list_sessions(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> list[PlannedSession]:
        """列出计划中的全部课次，供时间窗筛选与激活校验使用。"""
        ...
