"""Scenario Lab 开发边界：可推进时钟、补录训练、一键场景。

仅当 Settings.enable_scenario_lab 开启时由 bootstrap 挂载，生产构建不注册任何
/dev 路由。lab 是本地演示/联调能力：不进入 CI 与生产，业务写入仍走
canonical mutation + Outbox，与正式链路无差别。
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.dependencies.context import get_request_context
from app.api.errors import to_http_error
from app.coaching.domain.workout.models import WorkoutSource, WorkoutType
from app.coaching.ports.workout_mutation_store import WorkoutFeedbackMutation, WorkoutMutation
from app.common.errors import RunCoachError
from app.common.events import EventMetadata
from app.common.lab_clock import LabClock, LabClockError
from app.identity.application.request_context import RequestContext
from app.infrastructure.database.session import short_session
from app.infrastructure.seed.scenario import SCENARIOS, clear_user_coaching_data, seed_scenario

logger = logging.getLogger(__name__)

router = APIRouter()


def _lab_clock(request: Request) -> LabClock:
    """取进程内 LabClock；路由挂载已按开关门禁，此处兜底防错误装配。"""
    clock = request.app.state.clock
    if not isinstance(clock, LabClock):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="scenario_lab_disabled")
    return clock


class DevClockResponse(BaseModel):
    """虚拟时钟读数：业务"现在"与真实墙钟成对返回，便于展示偏移。"""

    virtual_now: datetime  # 业务"现在"（lab 时钟）
    wall_now: datetime  # 真实墙上时钟


class DevClockAdvanceRequest(BaseModel):
    """三种推进模式互斥：reset_to_wall / 设定绝对时刻 / 相对增量。"""

    reset_to_wall: bool = False  # 清除虚拟时刻，回到墙上时钟
    to: datetime | None = None  # 直接设定到某时刻（必须不早于当前虚拟时间）
    plus_days: int = Field(default=0, ge=0)  # 向前推的天数
    plus_hours: int = Field(default=0, ge=0)  # 向前推的小时数


@router.get("/api/v1/dev/clock", response_model=DevClockResponse)
async def get_dev_clock(
    request: Request,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
) -> DevClockResponse:
    """读取 lab 虚拟时钟；前端以 404 判定 lab 是否开启。"""
    lab = _lab_clock(request)
    return DevClockResponse(virtual_now=lab.now(), wall_now=datetime.now(UTC))


@router.post("/api/v1/dev/clock", response_model=DevClockResponse)
async def advance_dev_clock(
    body: DevClockAdvanceRequest,
    request: Request,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
) -> DevClockResponse:
    """推进 / 设定 / 重置虚拟时钟；Agent 下一轮对话自动按新 as_of 组装上下文。"""
    lab = _lab_clock(request)
    try:
        if body.reset_to_wall:
            await lab.reset_to_wall()
        elif body.to is not None:
            await lab.set_now(body.to)
        elif body.plus_days > 0 or body.plus_hours > 0:
            await lab.advance(days=body.plus_days, hours=body.plus_hours)
        else:
            raise LabClockError("dev_clock_advance_requires_mode")
    except LabClockError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return DevClockResponse(virtual_now=lab.now(), wall_now=datetime.now(UTC))


class DevWorkoutRequest(BaseModel):
    """补录一堂真实训练：时间由服务端按业务"今天"构造，不允许未来的训练。

    反馈字段全部缺省时只记课；任一反馈字段出现则同时写入一条主观反馈。
    """

    workout_type: WorkoutType  # 课种
    distance_m: float | None = None  # 距离（米）
    duration_s: int | None = None  # 时长（秒）
    avg_heart_rate: int | None = None  # 平均心率
    max_heart_rate: int | None = None  # 最高心率
    day_offset: int = Field(default=0, le=0)  # 相对业务今天：-1=昨天，0=今天
    perceived_exertion: int | None = Field(default=None, ge=1, le=10)  # 用力程度 RPE
    subjective_fatigue: int | None = Field(default=None, ge=1, le=10)  # 主观疲劳
    soreness: int | None = Field(default=None, ge=1, le=10)  # 酸痛
    note: str | None = None  # 自由备注


class DevWorkoutResponse(BaseModel):
    id: UUID  # 新训练 ID
    started_at: datetime  # 训练开始时间（业务时钟）
    workout_type: str  # 课种
    feedback_id: UUID | None = None  # 顺带写入的反馈 ID；未提交反馈为空
    recompute_version: int  # 同步重算后的状态快照版本号


@router.post("/api/v1/dev/workouts", response_model=DevWorkoutResponse)
async def record_dev_workout(
    body: DevWorkoutRequest,
    request: Request,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
) -> DevWorkoutResponse:
    """补录训练 + 可选内联反馈，并同步重算状态：演示时立刻看到新负荷。"""
    lab = _lab_clock(request)
    event_metadata = EventMetadata(
        correlation_id=request_context.request_id,
        trace_id=request_context.trace_id,
    )
    try:
        workout = await request.app.state.workout_command_service.record(
            user_id=request_context.user_id,
            mutation=WorkoutMutation(
                started_at=lab.now() + timedelta(days=body.day_offset),
                distance_m=body.distance_m,
                duration_s=body.duration_s,
                avg_heart_rate=body.avg_heart_rate,
                max_heart_rate=body.max_heart_rate,
                workout_type=body.workout_type,
                source=WorkoutSource.MANUAL,
            ),
            event_metadata=event_metadata,
        )
        feedback_id: UUID | None = None
        has_feedback = (
            body.perceived_exertion is not None
            or body.subjective_fatigue is not None
            or body.soreness is not None
            or body.note is not None
        )
        if has_feedback:
            feedback = await request.app.state.workout_feedback_command_service.record(
                user_id=request_context.user_id,
                workout_id=workout.id,
                mutation=WorkoutFeedbackMutation(
                    perceived_exertion=body.perceived_exertion,
                    subjective_fatigue=body.subjective_fatigue,
                    soreness=body.soreness,
                    note=body.note,
                ),
                event_metadata=event_metadata,
            )
            feedback_id = feedback.id
        # 记课后同步重算：正常链路由 Worker 的 outbox 事件异步触发，这里只为
        # 演示即时性提前执行；Worker 随后的重算会命中幂等短路，不会重复投影。
        result = await request.app.state.athlete_recompute_service.recompute_for_trigger(
            user_id=request_context.user_id,
            trigger=None,
            trigger_available_at=request_context.timestamp,
            event_metadata=event_metadata,
        )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    return DevWorkoutResponse(
        id=workout.id,
        started_at=workout.started_at,
        workout_type=workout.workout_type.value,
        feedback_id=feedback_id,
        recompute_version=result.snapshot.version,
    )


class DevRecomputeResponse(BaseModel):
    as_of: datetime  # 重算切点（业务时钟）
    version: int  # 生效快照版本号
    appended: bool  # False 表示证据未变化，复用了最新快照


@router.post("/api/v1/dev/athlete-state/recompute", response_model=DevRecomputeResponse)
async def recompute_dev_athlete_state(
    request: Request,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
) -> DevRecomputeResponse:
    """以业务"现在"为切点同步重算跑者状态；演示时免去等待 Worker 投影。"""
    try:
        result = await request.app.state.athlete_recompute_service.recompute_for_trigger(
            user_id=request_context.user_id,
            trigger=None,
            trigger_available_at=request_context.timestamp,
            event_metadata=EventMetadata(
                correlation_id=request_context.request_id,
                trace_id=request_context.trace_id,
            ),
        )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    return DevRecomputeResponse(
        as_of=result.snapshot.as_of,
        version=result.snapshot.version,
        appended=result.appended,
    )


class DevScenarioResponse(BaseModel):
    scenario: str  # 已应用场景名
    user_id: UUID  # 场景归属用户（当前 JWT 用户）
    workout_count: int  # 预置训练条数
    athlete_state_version: int  # 初始状态快照版本号


@router.post("/api/v1/dev/scenarios/{name}/apply", response_model=DevScenarioResponse)
async def apply_dev_scenario(
    name: str,
    request: Request,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
) -> DevScenarioResponse:
    """清空当前用户的 coaching 数据并按场景重种（锚点 = 业务"今天"）。"""
    spec = SCENARIOS.get(name)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown_scenario:{name}")
    lab = _lab_clock(request)
    try:
        async with short_session(request.app.state.sessions, commit=True) as session:
            await clear_user_coaching_data(session, user_id=request_context.user_id)
        seed = await seed_scenario(
            request.app.state.sessions,
            user_id=request_context.user_id,
            spec=spec,
            anchor=lab.now(),
            workout_command_service=request.app.state.workout_command_service,
            workout_feedback_command_service=request.app.state.workout_feedback_command_service,
            athlete_recompute_service=request.app.state.athlete_recompute_service,
            clock=request.app.state.clock,
        )
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    logger.info("dev_scenario_applied scenario=%s user_id=%s", spec.name, request_context.user_id)
    return DevScenarioResponse(
        scenario=spec.name,
        user_id=seed.user_id,
        workout_count=len(seed.workout_ids),
        athlete_state_version=seed.athlete_state_version,
    )
