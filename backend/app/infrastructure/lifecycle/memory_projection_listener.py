"""Phase 4 临时 best-effort TurnCommitted → Semantic Memory 投影。"""

from app.agent.lifecycle.events import LifecycleEvent, TurnCommitted
from app.memory.application.semantic_projection_service import (
    SemanticMemoryProjectionService,
)


class MemoryProjectionLifecycleListener:
    def __init__(self, service: SemanticMemoryProjectionService, projector_version: str) -> None:
        self._service = service
        self._projector_version = projector_version

    async def __call__(self, event: LifecycleEvent) -> None:
        if isinstance(event, TurnCommitted):
            await self._service.project_committed_turn(
                user_id=event.user_id,
                turn_id=event.turn_id,
                projector_version=self._projector_version,
            )
