"""Workout / Feedback canonical mutation 的事务端口。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.coaching.domain.workout.models import (
    Workout,
    WorkoutFeedback,
    WorkoutSource,
    WorkoutType,
    validate_subjective_scale,
)
from app.common.errors import DomainError
from app.common.events import EventMetadata


@dataclass(frozen=True)
class WorkoutMutation:
    """一次 Workout 版本写入的完整 canonical 字段。"""

    started_at: datetime  # 训练开始时间，必须带时区
    distance_m: float | None  # 距离（米）
    duration_s: int | None  # 时长（秒）
    avg_heart_rate: int | None  # 平均心率（次/分）
    max_heart_rate: int | None  # 最高心率（次/分）
    workout_type: WorkoutType  # 课型
    source: WorkoutSource  # 数据来源（种子导入 / 手动记录）

    def __post_init__(self) -> None:
        # 构造时即校验不变量：业务时间必须带时区，距离、时长必须为正。
        if self.started_at.tzinfo is None:
            raise DomainError("workout_started_at_requires_timezone")
        if self.distance_m is not None and self.distance_m < 0:
            raise DomainError("workout_distance_must_be_non_negative")
        if self.duration_s is not None and self.duration_s <= 0:
            raise DomainError("workout_duration_must_be_positive")


@dataclass(frozen=True)
class WorkoutFeedbackMutation:
    """一次主观反馈版本写入；业务时间由关联 Workout 决定。"""

    perceived_exertion: int | None  # sRPE 主观用力程度（1–10），未报告为 None
    subjective_fatigue: int | None  # 主观疲劳自评（1–10）
    soreness: int | None  # 酸痛自评（1–10）
    note: str | None  # 用户自由备注

    def __post_init__(self) -> None:
        # 三个主观量表统一在构造时校验范围，非法值尽早失败。
        validate_subjective_scale("perceived_exertion", self.perceived_exertion)
        validate_subjective_scale("subjective_fatigue", self.subjective_fatigue)
        validate_subjective_scale("soreness", self.soreness)


class WorkoutMutationStore(Protocol):
    """Workout / Feedback 写入事务端口；实现方负责落库与 durable event 投递。"""

    # 各方法在用户锁事务内写入新版本并登记 outbox 事件（available_at 为业务可见时间）。
    async def record_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        event_metadata: EventMetadata,
    ) -> Workout: ...

    async def update_workout(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        mutation: WorkoutMutation,
        event_metadata: EventMetadata,
    ) -> Workout: ...

    async def record_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback: ...

    async def update_feedback(
        self,
        *,
        user_id: UUID,
        feedback_id: UUID,
        mutation: WorkoutFeedbackMutation,
        event_metadata: EventMetadata,
    ) -> WorkoutFeedback: ...
