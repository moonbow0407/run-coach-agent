"""Workout / Feedback canonical mutation 的事务端口。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.workout.models import (
    Workout,
    WorkoutFeedback,
    WorkoutSource,
    WorkoutType,
    validate_subjective_scale,
)
from app.common.errors import DomainError
from app.common.events import EventMetadata


@dataclass(frozen=True)
class WorkoutMutation:
    """一次 Workout 版本写入的完整 canonical 字段。"""

    started_at: datetime
    distance_m: float | None
    duration_s: int | None
    avg_heart_rate: int | None
    max_heart_rate: int | None
    workout_type: WorkoutType
    source: WorkoutSource

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise DomainError("workout_started_at_requires_timezone")
        if self.distance_m is not None and self.distance_m < 0:
            raise DomainError("workout_distance_must_be_non_negative")
        if self.duration_s is not None and self.duration_s <= 0:
            raise DomainError("workout_duration_must_be_positive")


@dataclass(frozen=True)
class WorkoutFeedbackMutation:
    """一次主观反馈版本写入；业务时间由关联 Workout 决定。"""

    perceived_exertion: int | None
    subjective_fatigue: int | None
    soreness: int | None
    note: str | None

    def __post_init__(self) -> None:
        validate_subjective_scale("perceived_exertion", self.perceived_exertion)
        validate_subjective_scale("subjective_fatigue", self.subjective_fatigue)
        validate_subjective_scale("soreness", self.soreness)


class WorkoutMutationStore(Protocol):
    async def record_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> Workout: ...

    async def update_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> Workout: ...

    async def record_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback: ...

    async def update_feedback(
        self,
        *,
        user_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        available_at: datetime,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback: ...
