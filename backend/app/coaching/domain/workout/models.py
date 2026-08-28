from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError


class WorkoutType(StrEnum):
    EASY = "easy"
    TEMPO = "tempo"
    INTERVAL = "interval"
    LONG_RUN = "long_run"
    REST = "rest"
    RACE = "race"
    OTHER = "other"


class WorkoutSource(StrEnum):
    SEED = "seed"
    MANUAL = "manual"


def validate_subjective_scale(name: str, value: int | None) -> int | None:
    """主观量表统一为 1–10。None 表示用户未报告该项。"""
    if value is None:
        return None
    if not 1 <= value <= 10:
        raise DomainError(f"{name} 必须是 1–10 的整数")
    return value


@dataclass(frozen=True)
class Workout:
    id: UUID
    user_id: UUID
    started_at: datetime
    distance_m: float | None
    duration_s: int | None
    avg_heart_rate: int | None
    max_heart_rate: int | None
    workout_type: WorkoutType
    source: WorkoutSource
    created_at: datetime


@dataclass(frozen=True)
class WorkoutFeedback:
    """用户报告的原始主观事实，不等于 AthleteStateSnapshot 中的系统推导状态。"""

    id: UUID
    user_id: UUID
    workout_id: UUID
    perceived_exertion: int | None
    subjective_fatigue: int | None
    soreness: int | None
    note: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        validate_subjective_scale("perceived_exertion", self.perceived_exertion)
        validate_subjective_scale("subjective_fatigue", self.subjective_fatigue)
        validate_subjective_scale("soreness", self.soreness)
