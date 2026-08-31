"""Memory 持久化端口；复杂 merge 由同一用户短事务原子完成。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.memory.domain.episode import Episode, EpisodeCandidate
from app.memory.domain.semantic import SemanticMemory, SemanticMemoryCandidate


@dataclass(frozen=True)
class ProjectionResult:
    projection_key: str
    result_ids: tuple[UUID, ...]
    replayed: bool
    obsolete: bool = False


@dataclass(frozen=True)
class RankedSemanticCandidate:
    memory: SemanticMemory
    cosine_similarity: float


@dataclass(frozen=True)
class RankedEpisodeCandidate:
    episode: Episode
    cosine_similarity: float


class MemoryRepository(Protocol):
    async def apply_semantic_projection(
        self,
        *,
        user_id: UUID,
        projector_name: str,
        projector_version: str,
        projection_key: str,
        input_fingerprint: str,
        input_checkpoint: dict[str, object],
        candidates: tuple[SemanticMemoryCandidate, ...],
        embeddings: tuple[tuple[float, ...], ...],
        embedding_model: str,
        embedding_version: str,
        now: datetime,
    ) -> ProjectionResult: ...

    async def apply_episode_projection(
        self,
        *,
        user_id: UUID,
        projector_name: str,
        projector_version: str,
        projection_key: str,
        input_fingerprint: str,
        input_checkpoint: dict[str, object],
        candidate: EpisodeCandidate | None,
        embedding: tuple[float, ...] | None,
        embedding_model: str,
        embedding_version: str,
        now: datetime,
    ) -> ProjectionResult: ...

    async def has_retrievable(self, *, user_id: UUID, as_of: datetime) -> bool: ...

    async def search_semantic(
        self, *, user_id: UUID, as_of: datetime, query_embedding: tuple[float, ...], limit: int
    ) -> tuple[RankedSemanticCandidate, ...]: ...

    async def search_episodes(
        self, *, user_id: UUID, as_of: datetime, query_embedding: tuple[float, ...], limit: int
    ) -> tuple[RankedEpisodeCandidate, ...]: ...

    async def expire_due(self, *, user_id: UUID, as_of: datetime) -> int: ...
