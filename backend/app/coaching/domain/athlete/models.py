"""Athlete State 领域模型：跑者状态快照与疲劳 / 恢复等级。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum  # StrEnum：成员值即字符串，可直接序列化存储
from uuid import UUID

from app.coaching.domain.athlete.signals import AthleteStateSignal


class FatigueLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"  # 高疲劳：触发降负荷调整的必要前提之一


class RecoveryLevel(StrEnum):
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"


# 当前评估算法版本标识；写入每份快照，供重算幂等判断。
ALGORITHM_VERSION_V1 = "phase3.v1"


@dataclass(frozen=True)  # 不可变数据类：快照只追加新版本，不原地修改
class AthleteStateSnapshot:
    """系统结合事实证据推导出的跑者状态快照。

    快照是 Derived Domain State：只追加新版本，从不覆盖历史判断。
    seed-fixture 写入的 V1 仅用于 Phase 1/2 读取路径，不是 Evaluator 输出。
    """

    id: UUID
    user_id: UUID  # 归属用户，仓储层必须按此隔离数据
    version: int  # 单调递增的快照版本号，用于提案与激活的新鲜度校验
    as_of: datetime  # 状态投影基准时间：只汇总此时间点之前的证据
    fatigue_level: FatigueLevel | None  # 推导出的疲劳等级；证据不足为 None
    recovery_level: RecoveryLevel | None  # 推导出的恢复等级；证据不足为 None
    recent_training_load: float | None  # 当前 7 日窗可用 sRPE 负荷
    workout_completion_rate: float | None  # 计划完成率（Phase 3 恒为 None）
    training_load_coverage: float | None  # 当前窗 sRPE 覆盖率
    signals: tuple[AthleteStateSignal, ...]  # 可解释依据：结论来自哪些证据
    confidence: float | None  # 结论置信度 0.2–1.0
    algorithm_version: str  # 评估算法版本，如 phase3.v1
    created_at: datetime  # 快照写入时间
