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

SEMANTIC_LIMIT = 8  # 单次检索最多注入的语义记忆条数
EPISODE_LIMIT = 4  # 单次检索最多注入的情景记忆条数
SEMANTIC_CHAR_BUDGET = 1600  # 语义记忆注入 Context 的字符预算
EPISODE_CHAR_BUDGET = 2000  # 情景记忆注入 Context 的字符预算
CANDIDATE_SEMANTIC_LIMIT = 24  # 向量检索召回的语义候选上限（重排前）
CANDIDATE_EPISODE_LIMIT = 12  # 向量检索召回的情景候选上限（重排前）
EMBEDDING_DIMENSIONS = 1536  # 向量维度契约：嵌入结果必须严格一致
POLICY_VERSION = "phase4.v1"  # 重排与预算策略版本：结果可追溯


@dataclass(frozen=True)
class MemoryRetrievalResult:
    """一次检索的最终结果：入选记忆 + 是否因条数/预算被截断。"""

    semantic: tuple[SemanticMemory, ...]  # 入选的语义记忆条目
    episodic: tuple[Episode, ...]  # 入选的情景记忆条目
    semantic_truncated: bool  # 语义记忆是否被截断（未全部注入）
    episodic_truncated: bool  # 情景记忆是否被截断（未全部注入）
    policy_version: str = POLICY_VERSION  # 产生本结果的重排策略版本


class MemoryRetrievalService:
    """记忆检索服务：向量召回 → 确定性重排 → 条数与字符预算裁剪。"""

    def __init__(self, *, repository: MemoryRepository, embedding: EmbeddingProvider) -> None:
        self._repository = repository  # Memory 仓储端口：向量检索与双时间过滤
        self._embedding = embedding  # 向量化端口：查询文本转向量

    async def retrieve(
        self,
        *,
        user_id: UUID,
        query: str,
        as_of: datetime,
        semantic_limit: int = SEMANTIC_LIMIT,
        episode_limit: int = EPISODE_LIMIT,
    ) -> MemoryRetrievalResult:
        """检索与当前输入相关的长期记忆，供 Agent 每轮构造 Context。"""
        # 调用方请求的条数不允许突破模块默认上限。
        semantic_limit = min(max(0, semantic_limit), SEMANTIC_LIMIT)
        episode_limit = min(max(0, episode_limit), EPISODE_LIMIT)
        try:
            # 用户已无可检索记忆时短路返回，省去向量化与数据库查询。
            if not await self._repository.has_retrievable(user_id=user_id, as_of=as_of):
                return MemoryRetrievalResult((), (), False, False)
            # 向量化查询文本并校验供应商维度契约。
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
            # 检索失败必须显式暴露，不得静默当作"没有记忆"处理。
            raise MemoryRetrievalInfrastructureError("memory_retrieval_failed") from exc

        # 确定性重排：主键=加权得分（降序），平分时按时间新→旧、ID 兜底。
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
        # 按条数与字符预算裁剪，并记录是否发生截断。
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
    """语义记忆得分：相似度 0.6 为主，置信度/新近度/明示偏好各加权。"""
    explicit_boost = 1.0 if item.memory.origin is MemoryOrigin.EXPLICIT else 0.0
    return (
        0.60 * item.cosine_similarity
        + 0.20 * item.memory.confidence
        + 0.10 * _recency(item.memory.valid_from, as_of)
        + 0.10 * explicit_boost
    )


def _episode_score(item: RankedEpisodeCandidate, as_of: datetime) -> float:
    """情景记忆得分：相似度 0.65 为主，重要度与新近度加权。"""
    return (
        0.65 * item.cosine_similarity
        + 0.20 * item.episode.importance
        + 0.15 * _recency(item.episode.ended_at, as_of)
    )


def _recency(moment: datetime, as_of: datetime) -> float:
    """时间新近度打分：越新越接近 1，约每 180 天衰减一半。"""
    days = max(0.0, (as_of - moment).total_seconds() / 86400)
    return 1.0 / (1.0 + days / 180.0)


def _bounded[T](
    items: tuple[T, ...],
    *,
    limit: int,
    budget: int,
    text,
) -> tuple[tuple[T, ...], bool]:
    """按条数上限与字符预算顺序选取，返回（入选集合, 是否被截断）。

    [T] 是 PEP 695 泛型：同一实现同时服务语义与情景两种条目。
    """
    selected: list[T] = []
    used = 0
    for item in items:
        content = text(item)
        # 已达条数上限，或再放一条就超字符预算：停止并标记截断。
        if len(selected) >= limit or used + len(content) > budget:
            return tuple(selected), True
        selected.append(item)
        used += len(content)
    return tuple(selected), False
