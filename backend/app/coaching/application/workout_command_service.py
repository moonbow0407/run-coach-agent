"""Workout / Feedback 的正式 canonical write Application Services。"""

from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.workout_mutation_store import (
    WorkoutFeedbackMutation,
    WorkoutMutation,
    WorkoutMutationStore,
)
from app.common.clock import Clock
from app.common.events import EventMetadata
from app.common.ids import new_id


class WorkoutCommandService:
    """训练记录写入服务：生成新 id 与业务时间，委托 mutation store 落库。"""

    def __init__(self, store: WorkoutMutationStore, clock: Clock) -> None:
        self._store = store
        # clock 提供业务时间（available_at），测试可注入固定时钟。
        self._clock = clock

    async def record(
        self,
        *,
        user_id: UUID,
        mutation: WorkoutMutation,
        event_metadata: EventMetadata,
    ) -> Workout:
        """记录一次新训练：id 由服务端生成，落库并登记 durable event。"""
        return await self._store.record_workout(
            user_id=user_id,
            workout_id=new_id(),
            mutation=mutation,
            available_at=self._clock.now(),
            event_metadata=event_metadata,
        )

    async def update(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        event_metadata: EventMetadata,
    ) -> Workout:
        """更新已有训练字段：产生新版本并刷新 available_at。"""
        return await self._store.update_workout(
            user_id=user_id,
            workout_id=workout_id,
            mutation=mutation,
            available_at=self._clock.now(),
            event_metadata=event_metadata,
        )


class WorkoutFeedbackCommandService:
    """主观反馈写入服务；反馈总是关联到某次训练课。"""

    def __init__(self, store: WorkoutMutationStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def record(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutFeedbackMutation,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback:
        """为指定训练记录一条新的主观反馈（id 由服务端生成）。"""
        return await self._store.record_feedback(
            user_id=user_id,
            workout_id=workout_id,
            feedback_id=new_id(),
            mutation=mutation,
            available_at=self._clock.now(),
            event_metadata=event_metadata,
        )

    async def update(
        self,
        *,
        user_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback:
        """更新已有反馈内容：产生新版本并刷新 available_at。"""
        return await self._store.update_feedback(
            user_id=user_id,
            feedback_id=feedback_id,
            mutation=mutation,
            available_at=self._clock.now(),
            event_metadata=event_metadata,
        )
