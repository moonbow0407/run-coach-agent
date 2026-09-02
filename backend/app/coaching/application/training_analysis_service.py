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
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.plan_repository import PlanRepository
from app.coaching.ports.workout_repository import WorkoutRepository
from app.common.errors import NotFoundError

# 分析窗口内的训练条数硬上限；业余跑者 14 天远低于此。
ANALYSIS_WORKOUT_LIMIT = 200


def _latest_feedback_by_workout(
    feedback: list[WorkoutFeedback],
) -> dict[UUID, WorkoutFeedback]:
    """同一 workout 存在多条反馈时，确定性地取 as_of 时点最新一条参与计算。

    仓储按 created_at 升序返回，这里再做一次显式比较，
    避免"数据库返回顺序决定覆盖结果"的隐式依赖。
    """
    by_workout: dict[UUID, WorkoutFeedback] = {}
    for item in feedback:
        current = by_workout.get(item.workout_id)
        if current is None or item.created_at > current.created_at:
            by_workout[item.workout_id] = item
    return by_workout


def analyze_training_load_evidence(
    *,
    as_of: datetime,
    workouts: tuple[Workout, ...],
    feedback: tuple[WorkoutFeedback, ...],
) -> TrainingLoadAnalysis:
    """对已在同一事务中读取的 canonical evidence 执行确定性分析。"""
    return analyze_training_load(
        as_of=as_of,
        workouts=workouts,
        feedback_by_workout_id=_latest_feedback_by_workout(list(feedback)),
    )


class TrainingAnalysisService:
    """面向查询侧的训练分析服务：读仓储证据并委托纯领域函数计算。"""

    def __init__(self, workouts: WorkoutRepository, plans: PlanRepository) -> None:
        self._workouts = workouts
        self._plans = plans

    async def analyze_training_load(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
    ) -> TrainingLoadAnalysis:
        """读取最近两个 7 日窗的训练与反馈，计算负荷分析。"""
        # 一次拉取覆盖两个窗口的完整时间范围，窗口切分交给领域函数。
        start = as_of - timedelta(days=CURRENT_WINDOW_DAYS + PREVIOUS_WINDOW_DAYS)
        workouts = await self._workouts.list_between(
            user_id=user_id,
            start=start,
            end=as_of,
            limit=ANALYSIS_WORKOUT_LIMIT,
        )
        # 反馈读取上界就是 as_of：未来报告不允许污染历史分析。
        feedback = await self._workouts.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=[workout.id for workout in workouts],
            end=as_of,
        )
        return analyze_training_load_evidence(
            as_of=as_of,
            workouts=tuple(workouts),
            feedback=tuple(feedback),
        )

    async def analyze_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        as_of: datetime,
    ) -> WorkoutAnalysis:
        """分析单次训练：sRPE 负荷、质量课标记与同日计划课次上下文。"""
        workout = await self._workouts.get(user_id=user_id, workout_id=workout_id)
        # 训练不存在，或它发生在 as_of 之后（未来事实），都视为查不到。
        if workout is None or workout.started_at > as_of:
            raise NotFoundError("训练记录不存在")
        feedbacks = await self._workouts.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=[workout_id],
            end=as_of,
        )
        # 取 as_of 时点最新一条反馈；sRPE 只认 perceived_exertion。
        feedback = max(feedbacks, key=lambda item: item.created_at) if feedbacks else None
        rpe = feedback.perceived_exertion if feedback is not None else None
        same_day = ()
        # 同日计划课次只是上下文提示，不影响负荷数值。
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
