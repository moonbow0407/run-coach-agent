"""PlanChange 生命周期适配器：订阅 Turn 终态事件，不把 PlanChange 放进 agent 模块。"""

from app.agent.lifecycle.events import (
    LifecycleEvent,
    TurnCancelled,
    TurnCommitted,
    TurnFailed,
)
from app.coaching.application.plan_adaptation_service import PlanAdaptationService


class PlanChangeLifecycleListener:
    def __init__(self, service: PlanAdaptationService) -> None:
        self._service = service

    async def __call__(self, event: LifecycleEvent) -> None:
        if isinstance(event, TurnCommitted):
            await self._service.promote_draft_for_turn(
                user_id=event.user_id, turn_id=event.turn_id
            )
        elif isinstance(event, (TurnFailed, TurnCancelled)):
            await self._service.abandon_draft_for_turn(
                user_id=event.user_id, turn_id=event.turn_id
            )
