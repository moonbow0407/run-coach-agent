"""计划激活事务端口：在存储层原子完成提案确认与计划版本切换。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol  # Protocol：结构化鸭子类型，只约束方法签名，不要求继承
from uuid import UUID

from app.coaching.domain.plan.models import PlanChange, PlannedSession, TrainingPlan
from app.common.events import EventMetadata


@dataclass(frozen=True)  # 不可变数据类：激活结果一经返回不再变化
class PlanActivationResult:
    """一次原子激活的结果。already_confirmed 表示幂等返回。"""

    plan_change: PlanChange  # 激活后的提案（状态应为 CONFIRMED）
    resulting_plan: TrainingPlan | None  # 激活生成的新计划版本
    resulting_sessions: tuple[PlannedSession, ...]  # 新计划携带的课次列表
    already_confirmed: bool  # True 表示提案早已确认，本次是重复请求的幂等返回


class PlanActivationStore(Protocol):
    async def confirm(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        now: datetime,
        event_metadata: EventMetadata,
    ) -> PlanActivationResult:
        """在用户行锁下完成新鲜度检查、领域校验与版本激活。"""
        ...
