"""Semantic / Episode 提取器端口；模型输出必须落入有限领域候选。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.agent.models.message import Message
from app.memory.domain.episode import EpisodeCandidate, EpisodeType
from app.memory.domain.semantic import JsonValue, MemoryOrigin, SemanticMemoryType
from app.memory.ports.evidence_reader import ValidatedEvidence


@dataclass(frozen=True)
class ExtractedSemanticCandidate:
    """Extractor 的受限输出；Evidence identity 由 Application Service 绑定。"""

    type: SemanticMemoryType
    origin: MemoryOrigin
    subject_key: str
    value: JsonValue
    content: str
    valid_from: datetime
    valid_until: datetime | None


class SemanticMemoryExtractor(Protocol):
    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]: ...


class EpisodeDetector(Protocol):
    async def detect(
        self,
        *,
        type: EpisodeType,
        started_at: datetime,
        ended_at: datetime,
        evidence: tuple[ValidatedEvidence, ...],
    ) -> EpisodeCandidate | None: ...
