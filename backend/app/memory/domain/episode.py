"""Episodic Memory 的有限类型与完成条件。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError
from app.memory.domain.evidence import EvidenceSourceType


class EpisodeType(StrEnum):
    """Episode 的两种有限类型（v1 只支持这两类）。"""

    FATIGUE_AND_RECOVERY = "fatigue_and_recovery"  # 疲劳与恢复：高疲劳→调整→恢复的过程
    PLAN_ADAPTATION_OUTCOME = "plan_adaptation_outcome"  # 计划调整结果：降负荷调整后的效果


class EpisodeStatus(StrEnum):
    """Episode 生命周期状态。"""

    BUILDING = "building"  # 证据仍在累积，尚未观察到结果
    COMPLETED = "completed"  # 已包含结果证据，Episode 完结
    SUPERSEDED = "superseded"  # 被更新的同键 Episode 取代


class EpisodeEvidenceRole(StrEnum):
    """证据在 Episode 叙事中扮演的角色。"""

    TRIGGER = "trigger"  # 触发该 Episode 的证据（每个 Episode 必须有）
    CONTEXT = "context"  # 背景证据
    INTERVENTION = "intervention"  # 干预证据（如计划变更）
    OUTCOME = "outcome"  # 结果证据（如恢复良好的快照）


@dataclass(frozen=True)
class EpisodeEvidenceRef:
    """Episode 对一条证据的引用：来源身份 + 在 Episode 中扮演的角色。"""

    source_type: EvidenceSourceType  # 证据来源类型
    source_id: UUID  # 来源对象 ID
    source_occurred_at: datetime  # 证据发生时间（必须带时区）
    role: EpisodeEvidenceRole  # 在 Episode 中的角色（触发/背景/干预/结果）

    def __post_init__(self) -> None:
        # Episode 不能以其他 Episode 为证据（禁止自引用组合）。
        if self.source_type is EvidenceSourceType.EPISODE:
            raise DomainError("episode_composition_not_supported")
        # 时间必须带时区，保证跨时区比较与排序确定。
        if self.source_occurred_at.tzinfo is None:
            raise DomainError("episode_evidence_time_requires_timezone")


@dataclass(frozen=True)
class EpisodeCandidate:
    """检测器产出的 Episode 候选：落库前经领域规则校验。"""

    type: EpisodeType  # Episode 类型
    summary: str  # 摘要（检索命中后注入 Context，≤500 字）
    started_at: datetime  # 覆盖窗口起点
    ended_at: datetime  # 覆盖窗口终点
    importance: float  # 重要度 0–1，检索排序用
    logical_key: str  # 逻辑键：检测器认定的窗口身份，须与投影键一致
    evidence: tuple[EpisodeEvidenceRef, ...]  # 构成该 Episode 的证据引用

    def __post_init__(self) -> None:
        # 摘要非空且限长，控制注入 Context 的体积。
        if not self.summary.strip() or len(self.summary) > 500:
            raise DomainError("invalid_episode_summary")
        # 时间必须带时区，且窗口不能倒置。
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise DomainError("episode_time_requires_timezone")
        if self.ended_at < self.started_at:
            raise DomainError("invalid_episode_range")
        # 重要度限定在 0–1。
        if not 0 <= self.importance <= 1:
            raise DomainError("invalid_episode_importance")
        # 逻辑键非空且限长。
        if not self.logical_key or len(self.logical_key) > 200:
            raise DomainError("invalid_episode_logical_key")
        # 每个 Episode 必须能指出触发证据。
        if not any(item.role is EpisodeEvidenceRole.TRIGGER for item in self.evidence):
            raise DomainError("episode_requires_trigger")
        # 计划调整类 Episode 必须包含"计划变更"这一干预证据。
        if self.type is EpisodeType.PLAN_ADAPTATION_OUTCOME and not any(
            item.role is EpisodeEvidenceRole.INTERVENTION
            and item.source_type is EvidenceSourceType.PLAN_CHANGE
            for item in self.evidence
        ):
            raise DomainError("plan_episode_requires_intervention")

    @property
    def status(self) -> EpisodeStatus:
        """证据里已有结果即完结，否则仍处于证据累积阶段。"""
        return (
            EpisodeStatus.COMPLETED
            if any(item.role is EpisodeEvidenceRole.OUTCOME for item in self.evidence)
            else EpisodeStatus.BUILDING
        )


@dataclass(frozen=True)
class Episode:
    """已落库的情景记忆：一次有头有尾（或仍在累积）的训练事件。"""

    id: UUID
    user_id: UUID  # 归属用户
    type: EpisodeType  # Episode 类型
    summary: str  # 摘要（检索命中后注入 Context 的文本）
    started_at: datetime  # 事件窗口起点
    ended_at: datetime  # 事件窗口终点
    completed_at: datetime | None  # 完结时间（尚在累积时为空）
    superseded_at: datetime | None  # 被取代时间（未被取代时为空）
    importance: float  # 重要度 0–1
    status: EpisodeStatus  # 生命周期状态
    projector_name: str  # 产生本条目的投影器名
    projector_version: str  # 投影器版本（重投影兼容性判断）
    embedding_model: str  # 摘要向量化所用模型
    embedding_version: str  # 向量化模型版本
    embedding: tuple[float, ...]  # 摘要向量（pgvector 检索用）
    logical_key: str  # 逻辑键：同键新 Episode 取代旧条目
    superseded_by_id: UUID | None  # 取代者的 Episode ID
    created_at: datetime  # 落库时间
    updated_at: datetime  # 最近更新时间
