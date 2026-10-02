"""Memory 应用边界的 typed failures。"""

from app.common.errors import InfrastructureError


class MemoryRetrievalInfrastructureError(InfrastructureError):
    """查询 embedding 或 pgvector 检索失败；禁止退化为空 Memory。"""
