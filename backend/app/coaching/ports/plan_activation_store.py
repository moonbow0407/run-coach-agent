from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.plan.models import PlanChange, PlannedSession, TrainingPlan
from app.common.events import EventMetadata


@dataclass(frozen=True)
class PlanActivationResult:
    """一次原子激活的结果。already_confirmed 表示幂等返回。"""

    plan_change: PlanChange
    resulting_plan: TrainingPlan | None
    resulting_sessions: tuple[PlannedSession, ...]
    already_confirmed: bool


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
