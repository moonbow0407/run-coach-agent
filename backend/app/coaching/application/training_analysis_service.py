"""训练分析应用服务：按 as_of 装载证据并调用纯领域计算。"""

from datetime import datetime, timedelta
from uuid import UUID

from app.coaching.domain.analysis.models import (
    CURRENT_WINDOW_DAYS,
    PREVIOUS_WINDOW_DAYS,
    TrainingLoadAnalysis,
    WorkoutAnalysis,
)
from app.coaching.domain.analysis.training_load import (
    analyze_training_load,
    is_quality_workout,
    session_rpe_load,
)
from app.coaching.ports.plan_repository import PlanRepository
from app.coaching.ports.workout_repository import WorkoutRepository
from app.common.errors import NotFoundError

# 分析窗口内的训练条数硬上限；业余跑者 14 天远低于此。
ANALYSIS_WORKOUT_LIMIT = 200


class TrainingAnalysisService:
    def __init__(self, workouts: WorkoutRepository, plans: PlanRepository) -> None:
        self._workouts = workouts
        self._plans = plans

    async def analyze_training_load(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
    ) -> TrainingLoadAnalysis:
        start = as_of - timedelta(days=CURRENT_WINDOW_DAYS + PREVIOUS_WINDOW_DAYS)
        workouts = await self._workouts.list_between(
            user_id=user_id,
            start=start,
            end=as_of,
            limit=ANALYSIS_WORKOUT_LIMIT,
        )
        feedback = await self._workouts.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=[workout.id for workout in workouts],
        )
        by_workout = {item.workout_id: item for item in feedback}
        return analyze_training_load(
            as_of=as_of,
            workouts=workouts,
            feedback_by_workout_id=by_workout,
        )

    async def analyze_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        as_of: datetime,
    ) -> WorkoutAnalysis:
        workout = await self._workouts.get(user_id=user_id, workout_id=workout_id)
        if workout is None or workout.started_at > as_of:
            raise NotFoundError("训练记录不存在")
        feedbacks = await self._workouts.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=[workout_id],
        )
        feedback = max(feedbacks, key=lambda item: item.created_at) if feedbacks else None
        rpe = feedback.perceived_exertion if feedback is not None else None
        same_day = ()
        plan = await self._plans.get_active(user_id=user_id)
        if plan is not None:
            sessions = await self._plans.list_sessions(user_id=user_id, plan_id=plan.id)
            same_day = tuple(
                session
                for session in sessions
                if session.scheduled_date == workout.started_at.date()
            )
        return WorkoutAnalysis(
            workout=workout,
            feedback=feedback,
            session_rpe_load=session_rpe_load(
                duration_s=workout.duration_s,
                perceived_exertion=rpe,
            ),
            quality_session=is_quality_workout(workout.workout_type),
            same_day_planned_sessions=same_day,
        )
