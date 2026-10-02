"""训练目标仓储端口：GoalQueryService 读取 Active Goal 的抽象。"""

from typing import Protocol  # Protocol：结构化鸭子类型，只约束方法签名，不要求继承
from uuid import UUID

from app.coaching.domain.goal.models import TrainingGoal


class GoalRepository(Protocol):
    """训练目标只读仓储；实现方负责 user_id 隔离与 ACTIVE 过滤。"""

    async def get_active(self, *, user_id: UUID) -> TrainingGoal | None:
        """读取用户当前生效（ACTIVE）的训练目标；没有则返回 None。"""
        ...
