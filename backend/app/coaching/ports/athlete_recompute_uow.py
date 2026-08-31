"""Athlete State 重算的用户锁事务端口。"""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.coaching.domain.athlete.evaluator import AthleteStateAssessment
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.common.events import EventMetadata


class AthleteStateTriggerType(StrEnum):
    WORKOUT = "workout"
    WORKOUT_FEEDBACK = "workout_feedback"


@dataclass(frozen=True)
class AthleteStateTrigger:
    """触发重算的 canonical source identity；worker 事件不能替代源数据。"""

    source_type: AthleteStateTriggerType
    source_id: UUID
    available_at: datetime
    workout_id: UUID | None = None


@dataclass(frozen=True)
class AthleteStateEvidenceSet:
    """同一用户锁下读取的当前 canonical evidence 与 availability cutoff。"""

    latest_snapshot: AthleteStateSnapshot | None
    workouts: tuple[Workout, ...]
    feedback: tuple[WorkoutFeedback, ...]
    cutoff: datetime


class AthleteStateRecomputeTransaction(Protocol):
    async def load_evidence(
        self,
        *,
        trigger: AthleteStateTrigger | None,
        trigger_available_at: datetime,
        observed_at: datetime,
    ) -> AthleteStateEvidenceSet: ...

    async def append_snapshot(
        self,
        *,
        as_of: datetime,
        assessment: AthleteStateAssessment,
        created_at: datetime,
        event_metadata: EventMetadata,
    ) -> AthleteStateSnapshot: ...


class AthleteStateRecomputeUnitOfWork(Protocol):
    def transaction(
        self,
        *,
        user_id: UUID,
    ) -> AbstractAsyncContextManager[AthleteStateRecomputeTransaction]: ...
