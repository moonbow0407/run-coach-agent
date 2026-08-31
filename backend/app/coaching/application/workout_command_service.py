"""Workout / Feedback 的正式 canonical write Application Services。"""

from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.workout_mutation_store import (
    WorkoutFeedbackMutation,
    WorkoutMutation,
    WorkoutMutationStore,
)
from app.common.events import EventMetadata
from app.common.ids import new_id


class WorkoutCommandService:
    def __init__(self, store: WorkoutMutationStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def record(
        self,
        *,
        user_id: UUID,
        mutation: WorkoutMutation,
        event_metadata: EventMetadata,
    ) -> Workout:
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
        return await self._store.update_workout(
            user_id=user_id,
            workout_id=workout_id,
            mutation=mutation,
            available_at=self._clock.now(),
            event_metadata=event_metadata,
        )


class WorkoutFeedbackCommandService:
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
        return await self._store.update_feedback(
            user_id=user_id,
            feedback_id=feedback_id,
            mutation=mutation,
            available_at=self._clock.now(),
            event_metadata=event_metadata,
        )
