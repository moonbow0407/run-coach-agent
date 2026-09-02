"""训练记录查询服务：Agent 能力读取训练事实的领域入口。"""

from datetime import timedelta
from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.workout_repository import WorkoutRepository
from app.common.clock import Clock
from app.common.errors import DomainError

# 单次返回的训练记录硬上限：达到即视为可能截断，
# 由调用方作为 Tool Result Budget 元数据（truncated）显式报告。
RECENT_WORKOUTS_LIMIT = 50


class WorkoutQueryService:
    """训练记录与训练反馈的查询服务。入参校验在这里做，仓储只负责取数。"""

    def __init__(self, repository: WorkoutRepository, clock: Clock) -> None:
        self._repository = repository
        # clock 用于计算“最近 N 天”的时间窗口，测试可注入固定时钟。
        self._clock = clock

    async def get_recent_workouts(self, *, user_id: UUID, days: int) -> list[Workout]:
        """查询用户最近 N 天的训练记录（含上限，防止一次拉取过多）。"""
        if days <= 0:
            raise DomainError("days 必须为正整数")
        since = self._clock.now() - timedelta(days=days)
        return await self._repository.list_recent(
            user_id=user_id, since=since, limit=RECENT_WORKOUTS_LIMIT
        )

    async def get_workout(self, *, user_id: UUID, workout_id: UUID) -> Workout | None:
        """按 id 读取单条训练；不存在或不属于该用户返回 None。"""
        return await self._repository.get(user_id=user_id, workout_id=workout_id)

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        """读取某次训练的用户反馈；尚未报告返回 None。"""
        return await self._repository.get_feedback(user_id=user_id, workout_id=workout_id)
