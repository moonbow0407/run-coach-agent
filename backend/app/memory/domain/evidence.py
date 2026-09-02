"""Memory Evidence 的有限来源与独立性语义。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError


class EvidenceSourceType(StrEnum):
    """投影可引用的证据来源类型（已确认的持久来源）。"""

    MESSAGE = "message"  # 单条用户/助手消息
    TURN = "turn"  # 一轮已提交对话
    WORKOUT = "workout"  # 训练记录
    WORKOUT_FEEDBACK = "workout_feedback"  # 训练后主观反馈
    ATHLETE_STATE_SNAPSHOT = "athlete_state_snapshot"  # 跑者状态快照
    PLAN_CHANGE = "plan_change"  # 训练计划变更
    EPISODE = "episode"  # 已生成的情景记忆（仅用于溯源，不可再作证据）


class MemoryEvidenceRole(StrEnum):
    """证据对记忆断言的支持关系。"""

    SUPPORTS = "supports"  # 支持该记忆
    CORRECTS = "corrects"  # 修正既有记忆（补充更新）
    CONTRADICTS = "contradicts"  # 与既有记忆矛盾（需重新评估）


class EvidenceIndependenceRole(StrEnum):
    """证据独立性角色：决定独立来源计数（推断置信度依据）。"""

    PRIMARY = "primary"  # 独立主证据：可单独支撑一条记忆
    DERIVED_CONTEXT = "derived_context"  # 派生上下文：与主证据同源，不计独立组数


@dataclass(frozen=True)
class EvidenceRef:
    """经过 EvidenceReader 校验后的正式证据引用。"""

    source_type: EvidenceSourceType  # 证据来源类型
    source_id: UUID  # 来源对象 ID
    source_occurred_at: datetime  # 证据发生时间（必须带时区）
    evidence_group_key: str  # 独立性分组键：同组证据只算一个独立来源
    independence_role: EvidenceIndependenceRole  # 主证据 / 派生上下文
    role: MemoryEvidenceRole = MemoryEvidenceRole.SUPPORTS  # 对记忆的支持关系

    def __post_init__(self) -> None:
        # 时间必须带时区；分组键非空且限长（用于独立来源计数）。
        if self.source_occurred_at.tzinfo is None:
            raise DomainError("memory_evidence_time_requires_timezone")
        if not self.evidence_group_key or len(self.evidence_group_key) > 200:
            raise DomainError("invalid_evidence_group_key")


def primary_group_count(evidence: tuple[EvidenceRef, ...]) -> int:
    """统计证据中独立主证据的分组数：同组多条只算一次。"""
    return len(
        {
            item.evidence_group_key
            for item in evidence
            if item.independence_role is EvidenceIndependenceRole.PRIMARY
        }
    )
