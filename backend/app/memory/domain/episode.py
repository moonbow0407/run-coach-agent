"""Episodic Memory 的有限类型与完成条件。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError
from app.memory.domain.evidence import EvidenceSourceType


class EpisodeType(StrEnum):
    FATIGUE_AND_RECOVERY = "fatigue_and_recovery"
    PLAN_ADAPTATION_OUTCOME = "plan_adaptation_outcome"


class EpisodeStatus(StrEnum):
    BUILDING = "building"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


class EpisodeEvidenceRole(StrEnum):
    TRIGGER = "trigger"
    CONTEXT = "context"
    INTERVENTION = "intervention"
    OUTCOME = "outcome"


@dataclass(frozen=True)
class EpisodeEvidenceRef:
    source_type: EvidenceSourceType
    source_id: UUID
    source_occurred_at: datetime
    role: EpisodeEvidenceRole

    def __post_init__(self) -> None:
        if self.source_type is EvidenceSourceType.EPISODE:
            raise DomainError("episode_composition_not_supported")
        if self.source_occurred_at.tzinfo is None:
            raise DomainError("episode_evidence_time_requires_timezone")


@dataclass(frozen=True)
class EpisodeCandidate:
    type: EpisodeType
    summary: str
    started_at: datetime
    ended_at: datetime
    importance: float
    logical_key: str
    evidence: tuple[EpisodeEvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.summary.strip() or len(self.summary) > 500:
            raise DomainError("invalid_episode_summary")
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise DomainError("episode_time_requires_timezone")
        if self.ended_at < self.started_at:
            raise DomainError("invalid_episode_range")
        if not 0 <= self.importance <= 1:
            raise DomainError("invalid_episode_importance")
        if not self.logical_key or len(self.logical_key) > 200:
            raise DomainError("invalid_episode_logical_key")
        if not any(item.role is EpisodeEvidenceRole.TRIGGER for item in self.evidence):
            raise DomainError("episode_requires_trigger")
        if self.type is EpisodeType.PLAN_ADAPTATION_OUTCOME and not any(
            item.role is EpisodeEvidenceRole.INTERVENTION
            and item.source_type is EvidenceSourceType.PLAN_CHANGE
            for item in self.evidence
        ):
            raise DomainError("plan_episode_requires_intervention")

    @property
    def status(self) -> EpisodeStatus:
        return (
            EpisodeStatus.COMPLETED
            if any(item.role is EpisodeEvidenceRole.OUTCOME for item in self.evidence)
            else EpisodeStatus.BUILDING
        )


@dataclass(frozen=True)
class Episode:
    id: UUID
    user_id: UUID
    type: EpisodeType
    summary: str
    started_at: datetime
    ended_at: datetime
    completed_at: datetime | None
    superseded_at: datetime | None
    importance: float
    status: EpisodeStatus
    projector_name: str
    projector_version: str
    embedding_model: str
    embedding_version: str
    embedding: tuple[float, ...]
    logical_key: str
    superseded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime
