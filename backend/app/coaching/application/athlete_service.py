"""跑者状态查询服务。"""

from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_state_repository import AthleteStateRepository


class AthleteStateQueryService:
    """读取用户最新一份跑者状态快照（已有快照，不做现场计算）。"""

    def __init__(self, repository: AthleteStateRepository) -> None:
        self._repository = repository

    async def get_latest_athlete_state(
        self,
        *,
        user_id: UUID,
    ) -> AthleteStateSnapshot | None:
        return await self._repository.get_latest(user_id=user_id)
