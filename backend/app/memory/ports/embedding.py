"""Embedding 供应商无关端口。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    model: str
    version: str
    dimensions: int


class EmbeddingProvider(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch: ...
