"""Approved durable source 的统一只读边界。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.memory.domain.evidence import EvidenceIndependenceRole, EvidenceSourceType


@dataclass(frozen=True)
class ValidatedEvidence:
    source_type: EvidenceSourceType
    source_id: UUID
    source_occurred_at: datetime
    source_version: str
    evidence_group_key: str
    independence_role: EvidenceIndependenceRole
    facts: dict[str, object]


class EvidenceReader(Protocol):
    async def read_many(
        self,
        *,
        user_id: UUID,
        source_ids: tuple[tuple[EvidenceSourceType, UUID], ...],
    ) -> tuple[ValidatedEvidence, ...]: ...

    async def read_window(
        self,
        *,
        user_id: UUID,
        started_at: datetime,
        ended_at: datetime,
        source_types: tuple[EvidenceSourceType, ...],
    ) -> tuple[ValidatedEvidence, ...]:
        """读取有界 canonical evidence 候选；具体 Episode 证据由应用服务选择。"""
        ...
