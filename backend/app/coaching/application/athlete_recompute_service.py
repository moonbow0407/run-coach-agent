"""用户锁覆盖完整证据读取与提交的 Athlete State 重算入口。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.coaching.application.training_analysis_service import (
    analyze_training_load_evidence,
)
from app.coaching.domain.athlete.evaluator import (
    AthleteStateEvaluatorV1,
    AthleteStateEvidence,
)
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_recompute_uow import (
    AthleteStateRecomputeUnitOfWork,
    AthleteStateTrigger,
)
from app.common.clock import Clock
from app.common.errors import DomainError
from app.common.events import EventMetadata
from app.common.ids import new_id


@dataclass(frozen=True)
class AthleteStateRecomputeResult:
    snapshot: AthleteStateSnapshot
    appended: bool


class AthleteStateRecomputeService:
    def __init__(
        self,
        *,
        unit_of_work: AthleteStateRecomputeUnitOfWork,
        clock: Clock,
        evaluator: AthleteStateEvaluatorV1 | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._evaluator = evaluator or AthleteStateEvaluatorV1()

    async def recompute(
        self,
        *,
        user_id: UUID,
        as_of: datetime | None = None,
        event_metadata: EventMetadata | None = None,
    ) -> AthleteStateSnapshot:
        """显式重算入口；内部命令未提供关联 ID 时创建新的可信 correlation。"""
        result = await self.recompute_for_trigger(
            user_id=user_id,
            trigger=None,
            trigger_available_at=as_of if as_of is not None else self._clock.now(),
            event_metadata=(
                event_metadata or EventMetadata(correlation_id=new_id())
            ),
        )
        return result.snapshot

    async def recompute_for_trigger(
        self,
        *,
        user_id: UUID,
        trigger: AthleteStateTrigger | None,
        trigger_available_at: datetime,
        event_metadata: EventMetadata,
    ) -> AthleteStateRecomputeResult:
        if trigger_available_at.tzinfo is None:
            raise DomainError("athlete_state_trigger_requires_timezone")
        async with self._unit_of_work.transaction(user_id=user_id) as transaction:
            evidence = await transaction.load_evidence(
                trigger=trigger,
                trigger_available_at=trigger_available_at,
                observed_at=max(self._clock.now(), trigger_available_at),
            )
            latest = evidence.latest_snapshot
            if (
                latest is not None
                and evidence.cutoff <= latest.as_of
                and latest.algorithm_version == self._evaluator.algorithm_version
            ):
                return AthleteStateRecomputeResult(snapshot=latest, appended=False)

            projection_as_of = (
                max(evidence.cutoff, latest.as_of)
                if latest is not None
                else evidence.cutoff
            )
            analysis = analyze_training_load_evidence(
                as_of=projection_as_of,
                workouts=evidence.workouts,
                feedback=evidence.feedback,
            )
            assessment = self._evaluator.evaluate(
                AthleteStateEvidence(
                    as_of=projection_as_of,
                    recent_workouts=evidence.workouts,
                    recent_feedback=evidence.feedback,
                    training_load_analysis=analysis,
                )
            )
            snapshot = await transaction.append_snapshot(
                as_of=projection_as_of,
                assessment=assessment,
                created_at=self._clock.now(),
                event_metadata=event_metadata,
            )
            return AthleteStateRecomputeResult(snapshot=snapshot, appended=True)
