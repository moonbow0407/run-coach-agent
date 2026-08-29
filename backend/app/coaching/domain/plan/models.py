from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class PlanStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlanChangeStatus(StrEnum):
    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    STALE = "stale"
    ABANDONED = "abandoned"


class PlanChangeType(StrEnum):
    REDUCE_UPCOMING_LOAD = "reduce_upcoming_load"


class SessionType(StrEnum):
    EASY = "easy"
    TEMPO = "tempo"
    INTERVAL = "interval"
    LONG_RUN = "long_run"
    REST = "rest"
    RACE = "race"
    OTHER = "other"


@dataclass(frozen=True)
class TrainingPlan:
    """版本化的训练计划：调整必须生成新版本（Plan Version N+1），不覆盖历史。"""

    id: UUID
    user_id: UUID
    version: int
    goal_id: UUID | None
    status: PlanStatus
    starts_on: date
    ends_on: date
    created_at: datetime


@dataclass(frozen=True)
class PlannedSession:
    """计划中的单次训练课次；prescription 为结构化处方（距离 / 配速等）。"""

    id: UUID
    plan_id: UUID
    scheduled_date: date
    session_type: SessionType
    title: str
    prescription: dict[str, Any]


@dataclass(frozen=True)
class SessionChange:
    """PlanChange payload 中的单次课次替换。由领域服务生成，不由模型提供。"""

    source_session_id: UUID
    scheduled_date: date
    from_type: SessionType
    to_type: SessionType
    old_title: str
    new_title: str
    old_prescription: dict[str, Any]
    new_prescription: dict[str, Any]


@dataclass(frozen=True)
class PlanChangePayload:
    """结构化 Diff：horizon 与课次替换列表。"""

    horizon_days: int
    changes: tuple[SessionChange, ...]


@dataclass(frozen=True)
class PlanChange:
    """一次计划调整提案。DRAFT 不等于已激活的 Active Plan。"""

    id: UUID
    user_id: UUID
    from_plan_id: UUID
    from_plan_version: int
    based_on_state_id: UUID
    based_on_state_version: int
    source_turn_id: UUID | None
    source_run_id: UUID | None
    as_of: datetime
    change_type: PlanChangeType
    payload: PlanChangePayload
    reason: str
    status: PlanChangeStatus
    created_at: datetime
    resolved_at: datetime | None
    resulting_plan_id: UUID | None
