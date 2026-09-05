"""训练台只读查询边界：前端训练台的读取入口。

只调用 Coaching 查询服务，不拥有业务规则、不触碰 ORM；
user_id 只来自 JWT RequestContext。查询结果为空（无目标 /
无计划 / 无快照）按 404 报告，由前端渲染为对应的空状态。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies.context import get_request_context
from app.api.errors import to_http_error
from app.api.schemas.coaching import (
    ActiveGoalResponse,
    ActivePlanResponse,
    AthleteStateResponse,
    PlanSummaryResponse,
    WorkoutFeedbackResponse,
    WorkoutFeedbackSubmitRequest,
    WorkoutListResponse,
    WorkoutResponse,
)
from app.api.schemas.plan_changes import PlannedSessionResponse
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.workout_command_service import WorkoutFeedbackCommandService
from app.coaching.application.workout_service import WorkoutQueryService
from app.coaching.ports.workout_mutation_store import WorkoutFeedbackMutation
from app.common.errors import ConflictError, NotFoundError, RunCoachError
from app.common.events import EventMetadata
from app.identity.application.request_context import RequestContext

router = APIRouter()


# 从 app.state 取启动时装配好的各服务（路由保持无状态）。
def _goals(request: Request) -> GoalQueryService:
    return request.app.state.goal_service


def _plans(request: Request) -> PlanQueryService:
    return request.app.state.plan_service


def _athlete(request: Request) -> AthleteStateQueryService:
    return request.app.state.athlete_service


def _workouts(request: Request) -> WorkoutQueryService:
    return request.app.state.workout_service


def _workout_feedback_command(request: Request) -> WorkoutFeedbackCommandService:
    return request.app.state.workout_feedback_command_service


@router.get("/api/v1/goals/active", response_model=ActiveGoalResponse)
async def get_active_goal(
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ActiveGoalResponse:
    """读取当前生效的训练目标；无目标时按 404 返回，前端渲染为空状态。"""
    try:
        goal = await _goals(request).get_active_goal(user_id=request_context.user_id)
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    if goal is None:
        raise to_http_error(NotFoundError("当前没有生效的训练目标"))
    return ActiveGoalResponse(
        id=goal.id,
        goal_type=goal.goal_type.value,
        race_date=goal.race_date,
        race_distance_m=goal.race_distance_m,
        target_time_s=goal.target_time_s,
        status=goal.status.value,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


@router.get("/api/v1/plans/active", response_model=ActivePlanResponse)
async def get_active_plan(
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ActivePlanResponse:
    """读取当前生效计划及时间窗内的课次摘要；无计划时按 404 返回。"""
    try:
        summary = await _plans(request).get_active_plan_summary(
            user_id=request_context.user_id, as_of=request_context.timestamp
        )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    if summary is None:
        raise to_http_error(NotFoundError("当前没有生效的训练计划"))
    return ActivePlanResponse(
        plan=PlanSummaryResponse(
            id=summary.plan.id,
            version=summary.plan.version,
            status=summary.plan.status.value,
            starts_on=summary.plan.starts_on,
            ends_on=summary.plan.ends_on,
            goal_id=summary.plan.goal_id,
        ),
        window_start=summary.window_start,
        window_end=summary.window_end,
        truncated=summary.truncated,
        sessions=[
            PlannedSessionResponse(
                id=session.id,
                scheduled_date=session.scheduled_date,
                session_type=session.session_type.value,
                title=session.title,
                prescription=session.prescription,
            )
            for session in summary.sessions
        ],
    )


@router.get("/api/v1/athlete-state/latest", response_model=AthleteStateResponse)
async def get_latest_athlete_state(
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> AthleteStateResponse:
    """读取最近一次系统推导的跑者状态快照；从未生成过时按 404 返回。"""
    try:
        snapshot = await _athlete(request).get_latest_athlete_state(user_id=request_context.user_id)
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    if snapshot is None:
        raise to_http_error(NotFoundError("还没有跑者状态快照"))
    return AthleteStateResponse(
        id=snapshot.id,
        version=snapshot.version,
        as_of=snapshot.as_of,
        fatigue_level=(
            snapshot.fatigue_level.value if snapshot.fatigue_level is not None else None
        ),
        recovery_level=(
            snapshot.recovery_level.value if snapshot.recovery_level is not None else None
        ),
        recent_training_load=snapshot.recent_training_load,
        workout_completion_rate=snapshot.workout_completion_rate,
        training_load_coverage=snapshot.training_load_coverage,
        signals=[
            {
                "code": signal.code,
                "severity": signal.severity,
                "message": signal.message,
                "evidence_refs": list(signal.evidence_refs),
            }
            for signal in snapshot.signals
        ],
        confidence=snapshot.confidence,
        algorithm_version=snapshot.algorithm_version,
        created_at=snapshot.created_at,
    )


@router.get(
    "/api/v1/workouts/{workout_id}/feedback",
    response_model=WorkoutFeedbackResponse,
)
async def get_workout_feedback(
    workout_id: UUID,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> WorkoutFeedbackResponse:
    """单次训练的主观反馈：训练列表展开行懒加载使用，避免列表接口 N+1。"""
    try:
        workout = await _workouts(request).get_workout(
            user_id=request_context.user_id, workout_id=workout_id
        )
        if workout is None:
            raise NotFoundError("训练记录不存在")
        feedback = await _workouts(request).get_feedback(
            user_id=request_context.user_id, workout_id=workout_id
        )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    if feedback is None:
        raise to_http_error(NotFoundError("这次训练还没有主观反馈"))
    return WorkoutFeedbackResponse(
        id=feedback.id,
        user_id=feedback.user_id,
        workout_id=feedback.workout_id,
        perceived_exertion=feedback.perceived_exertion,
        subjective_fatigue=feedback.subjective_fatigue,
        soreness=feedback.soreness,
        note=feedback.note,
        created_at=feedback.created_at,
    )


@router.post(
    "/api/v1/workouts/{workout_id}/feedback",
    response_model=WorkoutFeedbackResponse,
)
async def submit_workout_feedback(
    workout_id: UUID,
    body: WorkoutFeedbackSubmitRequest,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> WorkoutFeedbackResponse:
    """提交或更新单次训练的主观反馈（RPE / 疲劳 / 酸痛 / 备注）。"""
    try:
        workout = await _workouts(request).get_workout(
            user_id=request_context.user_id, workout_id=workout_id
        )
        if workout is None:
            raise NotFoundError("训练记录不存在")

        existing = await _workouts(request).get_feedback(
            user_id=request_context.user_id, workout_id=workout_id
        )
        mutation = WorkoutFeedbackMutation(
            perceived_exertion=body.perceived_exertion,
            subjective_fatigue=body.subjective_fatigue,
            soreness=body.soreness,
            note=body.note,
        )
        event_metadata = EventMetadata(
            correlation_id=request_context.request_id,
            trace_id=request_context.trace_id,
        )
        service = _workout_feedback_command(request)
        if existing is None:
            try:
                feedback = await service.record(
                    user_id=request_context.user_id,
                    workout_id=workout_id,
                    mutation=mutation,
                    event_metadata=event_metadata,
                )
            except ConflictError:
                # 并发首次提交撞上唯一约束：改走更新已存在行。
                raced = await _workouts(request).get_feedback(
                    user_id=request_context.user_id, workout_id=workout_id
                )
                if raced is None:
                    raise
                feedback = await service.update(
                    user_id=request_context.user_id,
                    feedback_id=raced.id,
                    mutation=mutation,
                    event_metadata=event_metadata,
                )
        else:
            feedback = await service.update(
                user_id=request_context.user_id,
                feedback_id=existing.id,
                mutation=mutation,
                event_metadata=event_metadata,
            )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc

    return WorkoutFeedbackResponse(
        id=feedback.id,
        user_id=feedback.user_id,
        workout_id=feedback.workout_id,
        perceived_exertion=feedback.perceived_exertion,
        subjective_fatigue=feedback.subjective_fatigue,
        soreness=feedback.soreness,
        note=feedback.note,
        created_at=feedback.created_at,
    )


@router.get("/api/v1/workouts", response_model=WorkoutListResponse)
async def list_recent_workouts(
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
    days: Annotated[int, Query(ge=1, le=365)] = 30,  # 查询窗口天数（1-365，默认 30）
) -> WorkoutListResponse:
    """按天数窗口列出最近的训练记录。"""
    try:
        workouts = await _workouts(request).get_recent_workouts(
            user_id=request_context.user_id, days=days
        )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    return WorkoutListResponse(
        count=len(workouts),
        workouts=[
            WorkoutResponse(
                id=workout.id,
                started_at=workout.started_at,
                distance_m=workout.distance_m,
                duration_s=workout.duration_s,
                avg_heart_rate=workout.avg_heart_rate,
                max_heart_rate=workout.max_heart_rate,
                workout_type=workout.workout_type.value,
                source=workout.source.value,
                created_at=workout.created_at,
            )
            for workout in workouts
        ],
    )
