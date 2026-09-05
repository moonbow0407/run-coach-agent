"""安全策略取证：从 Coaching 查询服务读取状态与近期反馈备注。"""

from typing import Protocol
from uuid import UUID

from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.workout_service import WorkoutQueryService
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.tools.safety.constants import RECENT_FEEDBACK_LOOKBACK_DAYS


class SafetyEvidenceSource(Protocol):
    """SafetyGate 所需取证接口；测试可注入假实现。"""

    async def latest_athlete_state(self, *, user_id: UUID) -> AthleteStateSnapshot | None:
        """读取最新跑者状态快照。"""
        ...

    async def recent_feedback_notes(self, *, user_id: UUID) -> list[str]:
        """读取近期反馈备注文本（可能为空串，调用方过滤）。"""
        ...


class CoachingSafetyEvidenceSource:
    """用 Athlete / Workout 查询服务实现取证。"""

    def __init__(
        self,
        *,
        athlete_service: AthleteStateQueryService,
        workout_service: WorkoutQueryService,
        lookback_days: int = RECENT_FEEDBACK_LOOKBACK_DAYS,
    ) -> None:
        self._athlete = athlete_service
        self._workouts = workout_service
        self._lookback_days = lookback_days

    async def latest_athlete_state(self, *, user_id: UUID) -> AthleteStateSnapshot | None:
        return await self._athlete.get_latest_athlete_state(user_id=user_id)

    async def recent_feedback_notes(self, *, user_id: UUID) -> list[str]:
        feedbacks = await self._workouts.list_recent_feedback(
            user_id=user_id, days=self._lookback_days
        )
        return [item.note or "" for item in feedbacks]
