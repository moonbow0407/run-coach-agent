"""Athlete State 重算的用户锁事务端口。"""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.athlete.evaluator import AthleteStateAssessment
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.common.events import EventMetadata


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
