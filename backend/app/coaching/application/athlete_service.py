from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_state_repository import AthleteStateRepository


class AthleteStateQueryService:
    def __init__(self, repository: AthleteStateRepository) -> None:
        self._repository = repository

    async def get_latest_athlete_state(
        self,
        *,
        user_id: UUID,
    ) -> AthleteStateSnapshot | None:
        return await self._repository.get_latest(user_id=user_id)
