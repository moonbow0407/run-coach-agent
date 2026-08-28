from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class FatigueLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class RecoveryLevel(StrEnum):
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"


@dataclass(frozen=True)
class AthleteStateSnapshot:
    """系统结合事实证据推导出的跑者状态快照。

    Phase 1 只定义版本化与时间边界语义，不实现评估算法。
    测试与 seed 写入的快照仅用于验证读取路径。
    """

    id: UUID
    user_id: UUID
    version: int
    as_of: datetime
    fatigue_level: FatigueLevel | None
    recovery_level: RecoveryLevel | None
    recent_training_load: float | None
    workout_completion_rate: float | None
    confidence: float | None
    algorithm_version: str
    created_at: datetime
