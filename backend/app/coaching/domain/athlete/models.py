from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.coaching.domain.athlete.signals import AthleteStateSignal


class FatigueLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class RecoveryLevel(StrEnum):
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"


ALGORITHM_VERSION_V1 = "phase3.v1"


@dataclass(frozen=True)
class AthleteStateSnapshot:
    """系统结合事实证据推导出的跑者状态快照。

    快照是 Derived Domain State：只追加新版本，从不覆盖历史判断。
    seed-fixture 写入的 V1 仅用于 Phase 1/2 读取路径，不是 Evaluator 输出。
    """

    id: UUID
    user_id: UUID
    version: int
    as_of: datetime
    fatigue_level: FatigueLevel | None
    recovery_level: RecoveryLevel | None
    recent_training_load: float | None
    workout_completion_rate: float | None
    training_load_coverage: float | None
    signals: tuple[AthleteStateSignal, ...]
    confidence: float | None
    algorithm_version: str
    created_at: datetime
