"""Approved durable source 的统一只读边界。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.memory.domain.evidence import EvidenceIndependenceRole, EvidenceSourceType


@dataclass(frozen=True)
class ValidatedEvidence:
    """读取方拿到的已验证证据：来源身份 + 来源暴露的业务事实。"""

    source_type: EvidenceSourceType  # 证据来源类型
    source_id: UUID  # 来源对象 ID
    source_occurred_at: datetime  # 证据发生时间
    source_version: str  # 来源对象版本（检查点/幂等判断用）
    evidence_group_key: str  # 独立性分组键：同组证据只算一个独立来源
    independence_role: EvidenceIndependenceRole  # 主证据 / 派生上下文
    facts: dict[str, object]  # 业务事实字段（如 fatigue_level）


class EvidenceReader(Protocol):
    """证据统一只读端口（Protocol：实现方无需继承，按方法签名匹配）。"""

    # 按（来源类型, ID）精确批量读取证据
    async def read_many(
        self,
        *,
        user_id: UUID,
        source_ids: tuple[tuple[EvidenceSourceType, UUID], ...],
    ) -> tuple[ValidatedEvidence, ...]: ...

    async def read_window(
        self,
        *,
        user_id: UUID,
        started_at: datetime,
        ended_at: datetime,
        source_types: tuple[EvidenceSourceType, ...],
    ) -> tuple[ValidatedEvidence, ...]:
        """读取有界 canonical evidence 候选；具体 Episode 证据由应用服务选择。"""
        ...
