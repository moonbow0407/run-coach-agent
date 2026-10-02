"""Embedding 供应商无关端口。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingBatch:
    """一次批量向量化结果：向量与其产生模型的信息绑定在一起。"""

    vectors: tuple[tuple[float, ...], ...]  # 与输入文本顺序一一对应的向量
    model: str  # 使用的嵌入模型名
    version: str  # 模型版本（结果可追溯）
    dimensions: int  # 向量维度（须与调用方契约一致）


class EmbeddingProvider(Protocol):
    """向量化端口（Protocol：结构化鸭子类型，实现方无需继承本类）。"""

    # 把一批文本向量化；返回顺序必须与输入一一对应
    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch: ...
