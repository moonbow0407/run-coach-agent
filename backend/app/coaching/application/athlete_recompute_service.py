"""Athlete State 重算入口。不是 Agent Tool，由测试 / 未来事件驱动调用。"""

from datetime import datetime, timedelta
from uuid import UUID

from app.coaching.application.training_analysis_service import (
    ANALYSIS_WORKOUT_LIMIT,
    TrainingAnalysisService,
)
from app.coaching.domain.athlete.evaluator import AthleteStateEvaluatorV1, AthleteStateEvidence
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_state_repository import AthleteStateRepository
from app.coaching.ports.workout_repository import WorkoutRepository
from app.common.clock import Clock


class AthleteStateRecomputeService:
    def __init__(
        self,
        *,
        analysis: TrainingAnalysisService,
        workouts: WorkoutRepository,
        snapshots: AthleteStateRepository,
        clock: Clock,
        evaluator: AthleteStateEvaluatorV1 | None = None,
    ) -> None:
        self._analysis = analysis
        self._workouts = workouts
        self._snapshots = snapshots
        self._clock = clock
        self._evaluator = evaluator or AthleteStateEvaluatorV1()

    async def recompute(
        self,
        *,
        user_id: UUID,
        as_of: datetime | None = None,
    ) -> AthleteStateSnapshot:
        moment = as_of if as_of is not None else self._clock.now()
        analysis = await self._analysis.analyze_training_load(user_id=user_id, as_of=moment)
        start = moment - timedelta(days=14)
        workouts = await self._workouts.list_between(
            user_id=user_id,
            start=start,
            end=moment,
            limit=ANALYSIS_WORKOUT_LIMIT,
        )
        feedback = await self._workouts.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=[workout.id for workout in workouts],
        )
        assessment = self._evaluator.evaluate(
            AthleteStateEvidence(
                as_of=moment,
                recent_workouts=tuple(workouts),
                recent_feedback=tuple(feedback),
                training_load_analysis=analysis,
            )
        )
        return await self._snapshots.append_snapshot(
            user_id=user_id,
            as_of=moment,
            assessment=assessment,
            created_at=self._clock.now(),
        )
