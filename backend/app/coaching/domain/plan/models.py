from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class PlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


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
class ActivePlan:
    """当前生效计划及其课次。Phase 1 只读，不实现 Plan Adaptation。"""

    plan: TrainingPlan
    sessions: tuple[PlannedSession, ...]
