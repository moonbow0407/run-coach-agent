"""OpenAI-compatible Embedding adapter。"""

from openai import APIError, AsyncOpenAI

from app.common.errors import InfrastructureError
from app.memory.ports.embedding import EmbeddingBatch


class OpenAIEmbeddingProvider:
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
        if not texts:
            return EmbeddingBatch((), self._model, self._version, self._dimensions)
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=list(texts),
                dimensions=self._dimensions,
            )
        except APIError as exc:
            raise InfrastructureError("memory_embedding_failed") from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = tuple(tuple(float(value) for value in item.embedding) for item in ordered)
        if len(vectors) != len(texts) or any(len(vector) != self._dimensions for vector in vectors):
            raise InfrastructureError("memory_embedding_contract_mismatch")
        return EmbeddingBatch(vectors, self._model, self._version, self._dimensions)


class UnavailableEmbeddingProvider:
    """未配置外部模型时的显式失败边界；不生成零向量或随机向量。"""

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        raise InfrastructureError("memory_embedding_provider_not_configured")
