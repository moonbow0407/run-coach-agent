from typing import Protocol
from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot


class AthleteStateRepository(Protocol):
    """Athlete State 的跨模块只读端口；写入只允许经 Recompute UoW。"""

    async def get_latest(self, *, user_id: UUID) -> AthleteStateSnapshot | None: ...
