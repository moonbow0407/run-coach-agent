"""OpenAI-compatible Embedding adapter。

把文本转成固定维度向量，供记忆相似检索使用。
"""

from openai import APIError, AsyncOpenAI

from app.common.errors import InfrastructureError
from app.memory.ports.embedding import EmbeddingBatch


class OpenAIEmbeddingProvider:
    """文本向量化适配器：调用 embedding 模型产出与配置一致的向量批次。"""

    def __init__(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        version: str,
        dimensions: int = 1536,
    ) -> None:
        self._client = client
        self._model = model
        self._version = version
        self._dimensions = dimensions

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        """批量向量化文本；输入与产出的条数、维度必须严格一致。"""
        if not texts:  # 空输入：不调用外部服务，直接返回空批次
            return EmbeddingBatch((), self._model, self._version, self._dimensions)
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=list(texts),
                dimensions=self._dimensions,
            )
        except APIError as exc:
            raise InfrastructureError("memory_embedding_failed") from exc
        ordered = sorted(response.data, key=lambda item: item.index)  # 按 index 还原输入顺序
        vectors = tuple(tuple(float(value) for value in item.embedding) for item in ordered)
        if len(vectors) != len(texts) or any(len(vector) != self._dimensions for vector in vectors):
            # 条数或维度不符说明模型契约被破坏，fail fast
            raise InfrastructureError("memory_embedding_contract_mismatch")
        return EmbeddingBatch(vectors, self._model, self._version, self._dimensions)


class UnavailableEmbeddingProvider:
    """未配置外部模型时的显式失败边界；不生成零向量或随机向量。"""

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        raise InfrastructureError("memory_embedding_provider_not_configured")
