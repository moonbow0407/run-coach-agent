"""Athlete State 重算的用户锁事务端口。"""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.coaching.domain.athlete.evaluator import AthleteStateAssessment
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.common.events import EventMetadata


class AthleteStateTriggerType(StrEnum):
    WORKOUT = "workout"  # 新写入 / 更新了一条训练记录
    WORKOUT_FEEDBACK = "workout_feedback"  # 新写入 / 更新了一条主观反馈


@dataclass(frozen=True)
class AthleteStateTrigger:
    """触发重算的 canonical source identity；worker 事件不能替代源数据。"""

    source_type: AthleteStateTriggerType  # 触发来源类型（训练 / 反馈）
    source_id: UUID  # 触发源记录的 id
    available_at: datetime  # 该事实对下游可见的时间
    workout_id: UUID | None = None  # 来源为反馈时关联的训练 id


@dataclass(frozen=True)
class AthleteStateEvidenceSet:
    """同一用户锁下读取的当前 canonical evidence 与 availability cutoff。"""

    latest_snapshot: AthleteStateSnapshot | None  # 当前最新一版状态快照
    workouts: tuple[Workout, ...]  # 截止 cutoff 的全部训练记录
    feedback: tuple[WorkoutFeedback, ...]  # 截止 cutoff 的全部主观反馈
    cutoff: datetime  # 证据可见性截止线：晚于此时间的写入不参与本次计算


class AthleteStateRecomputeTransaction(Protocol):
    """一次重算事务内可执行的操作：先读证据，后追加快照。"""

    # 在用户锁下读取截至 cutoff 的 canonical 证据集合。
    async def load_evidence(
        self,
        *,
        trigger: AthleteStateTrigger | None,
        trigger_available_at: datetime,
        observed_at: datetime,
    ) -> AthleteStateEvidenceSet: ...

    # 把评估结果追加为新版快照（只追加，不覆盖历史）。
    async def append_snapshot(
        self,
        *,
        as_of: datetime,
        assessment: AthleteStateAssessment,
        created_at: datetime,
        event_metadata: EventMetadata,
    ) -> AthleteStateSnapshot: ...


class AthleteStateRecomputeUnitOfWork(Protocol):
    """以用户为粒度的锁单元：同一用户的重算串行执行，避免并发写快照。"""

    # 进入重算事务上下文（配合 async with）：获取用户锁，退出时释放。
    def transaction(
        self,
        *,
        user_id: UUID,
    ) -> AbstractAsyncContextManager[AthleteStateRecomputeTransaction]: ...
