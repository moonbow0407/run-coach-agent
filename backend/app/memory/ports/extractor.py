"""Semantic / Episode 提取器端口；模型输出必须落入有限领域候选。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.agent.models.message import Message
from app.memory.domain.episode import EpisodeCandidate, EpisodeType
from app.memory.domain.semantic import JsonValue, MemoryOrigin, SemanticMemoryType
from app.memory.ports.evidence_reader import ValidatedEvidence


@dataclass(frozen=True)
class ExtractedSemanticCandidate:
    """Extractor 的受限输出；Evidence identity 由 Application Service 绑定。"""

    type: SemanticMemoryType  # 记忆类型
    origin: MemoryOrigin  # 明示 / 推断
    subject_key: str  # 主体键
    value: JsonValue  # 断言值
    content: str  # 自然语言内容
    valid_from: datetime  # 业务有效期起点
    valid_until: datetime | None  # 业务有效期终点


class SemanticMemoryExtractor(Protocol):
    """语义记忆提取端口：从一轮已提交对话抽取受限的记忆候选。"""

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]: ...


class EpisodeDetector(Protocol):
    """Episode 检测端口：判断给定证据窗口是否构成 Episode 候选。"""

    async def detect(
        self,
        *,
        type: EpisodeType,
        started_at: datetime,
        ended_at: datetime,
        evidence: tuple[ValidatedEvidence, ...],
    ) -> EpisodeCandidate | None: ...
