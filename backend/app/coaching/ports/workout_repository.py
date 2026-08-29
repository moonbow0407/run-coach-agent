from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback


class WorkoutRepository(Protocol):
    async def list_recent(
        self,
        *,
        user_id: UUID,
        since: datetime,
        limit: int,
    ) -> list[Workout]:
        ...

    async def list_between(
        self,
        *,
        user_id: UUID,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[Workout]:
        """查询 start <= started_at <= end 的训练，强制 user_id 隔离。"""
        ...

    async def get(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> Workout | None:
        ...

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        ...

    async def list_feedback_for_workouts(
        self,
        *,
        user_id: UUID,
        workout_ids: list[UUID],
    ) -> list[WorkoutFeedback]:
        """批量读取 Feedback，避免按 workout 逐条查询。"""
        ...
