"""Semantic Memory 的有限类型、断言身份与生命周期规则。"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError
from app.memory.domain.evidence import EvidenceRef, primary_group_count

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonScalar, ...] | dict[str, JsonScalar]
_SUBJECT_KEY = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,119}$")


class SemanticMemoryType(StrEnum):
    AVAILABILITY_CONSTRAINT = "availability_constraint"
    SCHEDULE_PREFERENCE = "schedule_preference"
    TRAINING_PREFERENCE = "training_preference"
    ENVIRONMENT_PREFERENCE = "environment_preference"
    GOAL_PREFERENCE = "goal_preference"
    RECOVERY_PATTERN = "recovery_pattern"
    TRAINING_RESPONSE_PATTERN = "training_response_pattern"
    COMMUNICATION_PREFERENCE = "communication_preference"


class MemoryOrigin(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class SemanticMemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


@dataclass(frozen=True)
class SemanticMemoryCandidate:
    type: SemanticMemoryType
    origin: MemoryOrigin
    subject_key: str
    value: JsonValue
    content: str
    valid_from: datetime
    valid_until: datetime | None
    evidence: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not _SUBJECT_KEY.fullmatch(self.subject_key):
            raise DomainError("invalid_memory_subject_key")
        if not self.content.strip() or len(self.content) > 240:
            raise DomainError("invalid_memory_content")
        if self.valid_from.tzinfo is None:
            raise DomainError("memory_valid_from_requires_timezone")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None:
                raise DomainError("memory_valid_until_requires_timezone")
            if self.valid_until <= self.valid_from:
                raise DomainError("invalid_memory_validity")
        _normalize_value(self.value)
        if not self.evidence:
            raise DomainError("memory_requires_evidence")
        if self.origin is MemoryOrigin.EXPLICIT and primary_group_count(self.evidence) < 1:
            raise DomainError("explicit_memory_requires_primary_evidence")

    @property
    def assertion_hash(self) -> str:
        payload = {
            "type": self.type.value,
            "subject_key": self.subject_key,
            "value": _normalize_value(self.value),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def confidence(self) -> float:
        if self.origin is MemoryOrigin.EXPLICIT:
            return 1.0
        groups = primary_group_count(self.evidence)
        return min(0.90, 0.40 + 0.15 * groups)

    @property
    def initial_status(self) -> SemanticMemoryStatus:
        if self.origin is MemoryOrigin.EXPLICIT or self.confidence >= 0.70:
            return SemanticMemoryStatus.ACTIVE
        return SemanticMemoryStatus.CANDIDATE

    @property
    def source_occurred_at(self) -> datetime:
        return max(item.source_occurred_at for item in self.evidence)


@dataclass(frozen=True)
class SemanticMemory:
    id: UUID
    user_id: UUID
    type: SemanticMemoryType
    origin: MemoryOrigin
    subject_key: str
    value: JsonValue
    content: str
    assertion_hash: str
    confidence: float
    status: SemanticMemoryStatus
    valid_from: datetime
    valid_until: datetime | None
    activated_at: datetime | None
    expired_at: datetime | None
    source_occurred_at: datetime
    projector_name: str
    projector_version: str
    embedding_model: str
    embedding_version: str
    embedding: tuple[float, ...]
    superseded_by_id: UUID | None
    superseded_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _normalize_value(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        normalized = " ".join(value.strip().lower().split())
        if not normalized or len(normalized) > 160:
            raise DomainError("invalid_memory_value")
        return normalized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, tuple):
        if len(value) > 8:
            raise DomainError("memory_value_too_large")
        return tuple(_normalize_scalar(item) for item in value)
    if isinstance(value, dict):
        if len(value) > 8 or any(not key or len(key) > 60 for key in value):
            raise DomainError("memory_value_too_large")
        return {key: _normalize_scalar(value[key]) for key in sorted(value)}
    raise DomainError("invalid_memory_value")


def _normalize_scalar(value: JsonScalar) -> JsonScalar:
    if isinstance(value, str):
        normalized = " ".join(value.strip().lower().split())
        if not normalized or len(normalized) > 120:
            raise DomainError("invalid_memory_value")
        return normalized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise DomainError("invalid_memory_value")
