"""Coaching 应用层错误。"""

from app.coaching.domain.plan.models import PlanChange
from app.common.errors import ConflictError


class StalePlanChangeError(ConflictError):
    """确认时计划或状态版本已变，PlanChange 已标为 STALE。"""

    def __init__(self, plan_change: PlanChange) -> None:
        super().__init__("stale", code="stale")
        self.plan_change = plan_change
