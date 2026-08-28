from typing import Protocol
from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot


class AthleteStateRepository(Protocol):
    async def get_latest(self, *, user_id: UUID) -> AthleteStateSnapshot | None:
        ...
