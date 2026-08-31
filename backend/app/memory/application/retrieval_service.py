"""双时间过滤后的 pgvector 候选确定性重排与 Context 预算。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.memory.application.errors import MemoryRetrievalInfrastructureError
from app.memory.domain.episode import Episode
from app.memory.domain.semantic import MemoryOrigin, SemanticMemory
from app.memory.ports.embedding import EmbeddingProvider
from app.memory.ports.repositories import (
    MemoryRepository,
    RankedEpisodeCandidate,
    RankedSemanticCandidate,
)

SEMANTIC_LIMIT = 8
EPISODE_LIMIT = 4
SEMANTIC_CHAR_BUDGET = 1600
EPISODE_CHAR_BUDGET = 2000
CANDIDATE_SEMANTIC_LIMIT = 24
CANDIDATE_EPISODE_LIMIT = 12
EMBEDDING_DIMENSIONS = 1536
POLICY_VERSION = "phase4.v1"


@dataclass(frozen=True)
class MemoryRetrievalResult:
    semantic: tuple[SemanticMemory, ...]
    episodic: tuple[Episode, ...]
    semantic_truncated: bool
    episodic_truncated: bool
    policy_version: str = POLICY_VERSION


class MemoryRetrievalService:
    def __init__(self, *, repository: MemoryRepository, embedding: EmbeddingProvider) -> None:
        self._repository = repository
        self._embedding = embedding

    async def retrieve(
        self,
        *,
        user_id: UUID,
        query: str,
        as_of: datetime,
        semantic_limit: int = SEMANTIC_LIMIT,
        episode_limit: int = EPISODE_LIMIT,
    ) -> MemoryRetrievalResult:
        semantic_limit = min(max(0, semantic_limit), SEMANTIC_LIMIT)
        episode_limit = min(max(0, episode_limit), EPISODE_LIMIT)
        try:
            if not await self._repository.has_retrievable(user_id=user_id, as_of=as_of):
                return MemoryRetrievalResult((), (), False, False)
            batch = await self._embedding.embed((query,))
            if (
                batch.dimensions != EMBEDDING_DIMENSIONS
                or len(batch.vectors) != 1
                or len(batch.vectors[0]) != EMBEDDING_DIMENSIONS
            ):
                raise MemoryRetrievalInfrastructureError("memory_embedding_contract_mismatch")
            query_embedding = batch.vectors[0]
            semantic = await self._repository.search_semantic(
                user_id=user_id,
                as_of=as_of,
                query_embedding=query_embedding,
                limit=CANDIDATE_SEMANTIC_LIMIT,
            )
            episodic = await self._repository.search_episodes(
                user_id=user_id,
                as_of=as_of,
                query_embedding=query_embedding,
                limit=CANDIDATE_EPISODE_LIMIT,
            )
        except MemoryRetrievalInfrastructureError:
            raise
        except Exception as exc:
            raise MemoryRetrievalInfrastructureError("memory_retrieval_failed") from exc

        ranked_semantic = sorted(
            semantic,
            key=lambda item: (
                -_semantic_score(item, as_of),
                -item.memory.valid_from.timestamp(),
                str(item.memory.id),
            ),
        )
        ranked_episodic = sorted(
            episodic,
            key=lambda item: (
                -_episode_score(item, as_of),
                -item.episode.ended_at.timestamp(),
                str(item.episode.id),
            ),
        )
        selected_semantic, semantic_truncated = _bounded(
            tuple(item.memory for item in ranked_semantic),
            limit=semantic_limit,
            budget=SEMANTIC_CHAR_BUDGET,
            text=lambda item: item.content,
        )
        selected_episodes, episodic_truncated = _bounded(
            tuple(item.episode for item in ranked_episodic),
            limit=episode_limit,
            budget=EPISODE_CHAR_BUDGET,
            text=lambda item: item.summary,
        )
        return MemoryRetrievalResult(
            semantic=selected_semantic,
            episodic=selected_episodes,
            semantic_truncated=semantic_truncated,
            episodic_truncated=episodic_truncated,
        )


def _semantic_score(item: RankedSemanticCandidate, as_of: datetime) -> float:
    explicit_boost = 1.0 if item.memory.origin is MemoryOrigin.EXPLICIT else 0.0
    return (
        0.60 * item.cosine_similarity
        + 0.20 * item.memory.confidence
        + 0.10 * _recency(item.memory.valid_from, as_of)
        + 0.10 * explicit_boost
    )


def _episode_score(item: RankedEpisodeCandidate, as_of: datetime) -> float:
    return (
        0.65 * item.cosine_similarity
        + 0.20 * item.episode.importance
        + 0.15 * _recency(item.episode.ended_at, as_of)
    )


def _recency(moment: datetime, as_of: datetime) -> float:
    days = max(0.0, (as_of - moment).total_seconds() / 86400)
    return 1.0 / (1.0 + days / 180.0)


def _bounded[T](
    items: tuple[T, ...],
    *,
    limit: int,
    budget: int,
    text,
) -> tuple[tuple[T, ...], bool]:
    selected: list[T] = []
    used = 0
    for item in items:
        content = text(item)
        if len(selected) >= limit or used + len(content) > budget:
            return tuple(selected), True
        selected.append(item)
        used += len(content)
    return tuple(selected), False
