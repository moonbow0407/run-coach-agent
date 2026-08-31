"""训练台只读查询 API 的响应模型。

这些模型面向前端训练台：字段镜像 Coaching Domain 模型，
枚举一律序列化为字符串，时间保持 ISO 字符串（FastAPI 默认行为）。
课次响应直接复用计划调整 API 的 PlannedSessionResponse，
保证两处对“一节课”的字段口径完全一致。
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.schemas.plan_changes import PlannedSessionResponse


class ActiveGoalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    goal_type: str
    race_date: date | None
    race_distance_m: int | None
    target_time_s: int | None
    status: str
    created_at: datetime
    updated_at: datetime


class PlanSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    status: str
    starts_on: date
    ends_on: date
    goal_id: UUID | None


class ActivePlanResponse(BaseModel):
    """当前生效计划的受控摘要：窗口 = as_of 所在 ISO 周 ∪ 未来 14 天。"""

    model_config = ConfigDict(extra="forbid")

    plan: PlanSummaryResponse
    window_start: date
    window_end: date
    truncated: bool
    sessions: list[PlannedSessionResponse]


class AthleteStateSignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str
    evidence_refs: list[str]


class AthleteStateResponse(BaseModel):
    """系统推导的跑者状态快照（区别于用户报告的主观反馈）。

    algorithm_version / as_of / confidence 面向前端完整展示，
    让“系统认为你现在怎么样”这件事可解释、可追溯。
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    as_of: datetime
    fatigue_level: str | None
    recovery_level: str | None
    recent_training_load: float | None
    workout_completion_rate: float | None
    training_load_coverage: float | None
    signals: list[AthleteStateSignalResponse]
    confidence: float | None
    algorithm_version: str
    created_at: datetime


class WorkoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    started_at: datetime
    distance_m: float | None
    duration_s: int | None
    avg_heart_rate: int | None
    max_heart_rate: int | None
    workout_type: str
    source: str
    created_at: datetime


class WorkoutListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    workouts: list[WorkoutResponse]


class WorkoutFeedbackResponse(BaseModel):
    """用户报告的主观事实（RPE / 疲劳 / 酸痛），不是系统推导的状态。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_id: UUID
    workout_id: UUID
    perceived_exertion: int | None
    subjective_fatigue: int | None
    soreness: int | None
    note: str | None
    created_at: datetime
