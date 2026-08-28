from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class GoalType(StrEnum):
    RACE = "race"
    GENERAL = "general"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TrainingGoal:
    id: UUID
    user_id: UUID
    goal_type: GoalType
    race_date: date | None
    race_distance_m: int | None
    target_time_s: int | None
    status: GoalStatus
    created_at: datetime
    updated_at: datetime
