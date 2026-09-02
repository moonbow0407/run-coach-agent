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
    """当前生效的训练目标。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    goal_type: str  # 目标类型（如某场比赛的备赛目标）
    race_date: date | None  # 比赛日期
    race_distance_m: int | None  # 比赛距离（米）
    target_time_s: int | None  # 目标完赛时间（秒）
    status: str  # 目标状态
    created_at: datetime  # 记录创建时间
    updated_at: datetime  # 记录最近更新时间


class PlanSummaryResponse(BaseModel):
    """训练计划摘要信息。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int  # 计划版本号（每次调整递增）
    status: str  # 计划状态
    starts_on: date  # 计划开始日期
    ends_on: date  # 计划结束日期
    goal_id: UUID | None


class ActivePlanResponse(BaseModel):
    """当前生效计划的受控摘要：窗口 = as_of 所在 ISO 周 ∪ 未来 14 天。"""

    model_config = ConfigDict(extra="forbid")

    plan: PlanSummaryResponse  # 计划摘要
    window_start: date  # 摘要覆盖时间窗的起点
    window_end: date  # 摘要覆盖时间窗的终点
    truncated: bool  # 窗口内课次是否因数量被截断
    sessions: list[PlannedSessionResponse]  # 窗口内的训练课列表


class AthleteStateSignalResponse(BaseModel):
    """单条状态信号：系统发现的异常或提示。"""

    model_config = ConfigDict(extra="forbid")

    code: str  # 信号代码
    severity: str  # 严重程度
    message: str  # 面向用户的说明文字
    evidence_refs: list[str]  # 证据引用（指向支撑该信号的数据）


class AthleteStateResponse(BaseModel):
    """系统推导的跑者状态快照（区别于用户报告的主观反馈）。

    algorithm_version / as_of / confidence 面向前端完整展示，
    让“系统认为你现在怎么样”这件事可解释、可追溯。
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int  # 快照版本号（每次重算递增）
    as_of: datetime  # 快照对应的时间点
    fatigue_level: str | None  # 系统判定的疲劳等级
    recovery_level: str | None  # 系统判定的恢复等级
    recent_training_load: float | None  # 近期训练负荷
    workout_completion_rate: float | None  # 训练完成率
    training_load_coverage: float | None  # 训练负荷覆盖度
    signals: list[AthleteStateSignalResponse]  # 状态信号列表
    confidence: float | None  # 本次推导的置信度
    algorithm_version: str  # 生成快照的算法版本
    created_at: datetime  # 快照创建时间


class WorkoutResponse(BaseModel):
    """一次训练（workout）记录。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    started_at: datetime  # 训练开始时间
    distance_m: float | None  # 距离（米）
    duration_s: int | None  # 时长（秒）
    avg_heart_rate: int | None  # 平均心率
    max_heart_rate: int | None  # 最大心率
    workout_type: str  # 训练类型
    source: str  # 数据来源（如手表导入）
    created_at: datetime  # 记录创建时间


class WorkoutListResponse(BaseModel):
    """最近训练列表。"""

    model_config = ConfigDict(extra="forbid")

    count: int  # 训练条数
    workouts: list[WorkoutResponse]  # 训练记录列表


class WorkoutFeedbackResponse(BaseModel):
    """用户报告的主观事实（RPE / 疲劳 / 酸痛），不是系统推导的状态。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_id: UUID
    workout_id: UUID
    perceived_exertion: int | None  # 自觉用力程度（RPE）
    subjective_fatigue: int | None  # 主观疲劳评分
    soreness: int | None  # 酸痛评分
    note: str | None  # 用户备注
    created_at: datetime  # 反馈提交时间
