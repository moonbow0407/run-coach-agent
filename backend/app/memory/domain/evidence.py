"""Memory Evidence 的有限来源与独立性语义。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError


class EvidenceSourceType(StrEnum):
    MESSAGE = "message"
    TURN = "turn"
    WORKOUT = "workout"
    WORKOUT_FEEDBACK = "workout_feedback"
    ATHLETE_STATE_SNAPSHOT = "athlete_state_snapshot"
    PLAN_CHANGE = "plan_change"
    EPISODE = "episode"


class MemoryEvidenceRole(StrEnum):
    SUPPORTS = "supports"
    CORRECTS = "corrects"
    CONTRADICTS = "contradicts"


class EvidenceIndependenceRole(StrEnum):
    PRIMARY = "primary"
    DERIVED_CONTEXT = "derived_context"


@dataclass(frozen=True)
class EvidenceRef:
    """经过 EvidenceReader 校验后的正式证据引用。"""

    source_type: EvidenceSourceType
    source_id: UUID
    source_occurred_at: datetime
    evidence_group_key: str
    independence_role: EvidenceIndependenceRole
    role: MemoryEvidenceRole = MemoryEvidenceRole.SUPPORTS

    def __post_init__(self) -> None:
        if self.source_occurred_at.tzinfo is None:
            raise DomainError("memory_evidence_time_requires_timezone")
        if not self.evidence_group_key or len(self.evidence_group_key) > 200:
            raise DomainError("invalid_evidence_group_key")


def primary_group_count(evidence: tuple[EvidenceRef, ...]) -> int:
    return len(
        {
            item.evidence_group_key
            for item in evidence
            if item.independence_role is EvidenceIndependenceRole.PRIMARY
        }
    )
