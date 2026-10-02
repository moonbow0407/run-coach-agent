"""Memory 持久化端口；复杂 merge 由同一用户短事务原子完成。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.memory.domain.episode import Episode, EpisodeCandidate
from app.memory.domain.semantic import SemanticMemory, SemanticMemoryCandidate


@dataclass(frozen=True)
class ProjectionResult:
    """一次投影在仓储端合并后的结果（相同输入重放结果不变）。"""

    projection_key: str  # 投影键：同一逻辑对象的唯一标识
    result_ids: tuple[UUID, ...]  # 本次投影创建/更新的记忆 ID
    replayed: bool  # 是否为重放（输入指纹与上次一致或输入已过时）
    obsolete: bool = False  # 输入来源集合是已处理投影的子集（过时输入，未做变更）


@dataclass(frozen=True)
class RankedSemanticCandidate:
    """向量检索命中的语义记忆及其与查询的余弦相似度。"""

    memory: SemanticMemory  # 命中的记忆条目
    cosine_similarity: float  # 与查询向量的余弦相似度


@dataclass(frozen=True)
class RankedEpisodeCandidate:
    """向量检索命中的情景记忆及其与查询的余弦相似度。"""

    episode: Episode  # 命中的情景记忆
    cosine_similarity: float  # 与查询向量的余弦相似度


class MemoryRepository(Protocol):
    """Memory 仓储端口（Protocol）：投影合并与检索由基础设施层实现。"""

    # 以投影键幂等合并语义记忆：merge 在同一用户短事务内原子完成
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

    # 以投影键幂等合并情景记忆；candidate 为 None 表示窗口未成形
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

    # 该用户在 as_of 时刻是否还有可检索记忆（无则检索侧短路）
    async def has_retrievable(self, *, user_id: UUID, as_of: datetime) -> bool: ...

    # 双时间过滤（生命周期 + 业务有效期）后的 pgvector 近邻检索
    async def search_semantic(
        self, *, user_id: UUID, as_of: datetime, query_embedding: tuple[float, ...], limit: int
    ) -> tuple[RankedSemanticCandidate, ...]: ...

    # 同 search_semantic，检索对象为情景记忆
    async def search_episodes(
        self, *, user_id: UUID, as_of: datetime, query_embedding: tuple[float, ...], limit: int
    ) -> tuple[RankedEpisodeCandidate, ...]: ...

    # 把到期记忆标记为过期，返回处理条数（生命周期维护）
    async def expire_due(self, *, user_id: UUID, as_of: datetime) -> int: ...
