"""训练记录仓储端口：Workout 与 Feedback 事实的只读访问。"""

from datetime import datetime
from typing import Protocol  # Protocol：结构化鸭子类型，只约束方法签名，不要求继承
from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback


class WorkoutRepository(Protocol):
    """训练记录只读仓储；实现方负责 user_id 隔离。"""

    async def list_recent(
        self,
        *,
        user_id: UUID,
        since: datetime,
        limit: int,
    ) -> list[Workout]:
        """查询 since 之后的训练记录，最多 limit 条（防止一次拉取过多）。"""
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
        """按 id 读取单条训练；不存在或不属于该用户返回 None。"""
        ...

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        """读取某次训练的用户反馈；尚未报告返回 None。"""
        ...

    async def list_feedback_for_workouts(
        self,
        *,
        user_id: UUID,
        workout_ids: list[UUID],
        end: datetime,
    ) -> list[WorkoutFeedback]:
        """批量读取 Feedback，避免按 workout 逐条查询。

        end 是证据时间上界：created_at > end 的反馈不得进入任何状态计算，
        否则未来报告会污染历史快照。结果按 created_at 升序返回，
        同一 workout 存在多条反馈时，遍历顺序即"从旧到新"。
        """
        ...
