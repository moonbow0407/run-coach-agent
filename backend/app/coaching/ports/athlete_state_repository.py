from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.athlete.evaluator import AthleteStateAssessment
from app.coaching.domain.athlete.models import AthleteStateSnapshot


class AthleteStateRepository(Protocol):
    async def get_latest(self, *, user_id: UUID) -> AthleteStateSnapshot | None:
        ...

    async def append_snapshot(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
        assessment: AthleteStateAssessment,
        created_at: datetime,
    ) -> AthleteStateSnapshot:
        """在用户行锁下追加快照。相同 as_of + 相同评估返回已有行。"""
        ...
