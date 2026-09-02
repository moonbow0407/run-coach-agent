"""Semantic Memory 的有限类型、断言身份与生命周期规则。"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError
from app.memory.domain.evidence import EvidenceRef, primary_group_count

# 记忆值允许的标量与容器形状（type 别名：PEP 695 类型别名语法）
type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonScalar, ...] | dict[str, JsonScalar]
# 主体键格式：字母/数字开头，仅含小写字母、数字、: _ -，最长 120 字符
_SUBJECT_KEY = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,119}$")


class SemanticMemoryType(StrEnum):
    """语义记忆的有限类型：v1 只允许记忆这 8 类事实。"""

    AVAILABILITY_CONSTRAINT = "availability_constraint"  # 可用时间约束（如工作日无法训练）
    SCHEDULE_PREFERENCE = "schedule_preference"  # 作息排程偏好（如偏好晨跑）
    TRAINING_PREFERENCE = "training_preference"  # 训练内容偏好（如喜欢长距离）
    ENVIRONMENT_PREFERENCE = "environment_preference"  # 环境偏好（场地、天气等）
    GOAL_PREFERENCE = "goal_preference"  # 目标偏好（目标赛事与成绩）
    RECOVERY_PATTERN = "recovery_pattern"  # 恢复规律（如赛后需两天恢复）
    TRAINING_RESPONSE_PATTERN = "training_response_pattern"  # 对负荷的响应规律
    COMMUNICATION_PREFERENCE = "communication_preference"  # 沟通偏好（如简短回复）


class MemoryOrigin(StrEnum):
    """记忆来源：决定置信度与新旧替代规则。"""

    EXPLICIT = "explicit"  # 用户在对话中明示
    INFERRED = "inferred"  # 系统从证据中推断


class SemanticMemoryStatus(StrEnum):
    """语义记忆生命周期状态。"""

    CANDIDATE = "candidate"  # 候选：置信度不足，暂不注入 Context
    ACTIVE = "active"  # 生效：可被检索使用
    SUPERSEDED = "superseded"  # 被更新的断言取代
    EXPIRED = "expired"  # 已过期失效


@dataclass(frozen=True)
class SemanticMemoryCandidate:
    """语义记忆候选：断言身份、置信度与初始状态由领域规则统一推导。"""

    type: SemanticMemoryType  # 记忆类型
    origin: MemoryOrigin  # 明示 / 推断
    subject_key: str  # 主体键：断言关于"谁/什么"的规范化标识
    value: JsonValue  # 断言值（规范化的小写标量/元组/字典）
    content: str  # 自然语言内容（≤240 字，检索命中后注入 Context）
    valid_from: datetime  # 业务有效期起点
    valid_until: datetime | None  # 业务有效期终点（长期有效为空）
    evidence: tuple[EvidenceRef, ...]  # 支撑本断言的证据引用

    def __post_init__(self) -> None:
        # 主体键必须符合规范格式，保证同一主题的断言可归并比较。
        if not _SUBJECT_KEY.fullmatch(self.subject_key):
            raise DomainError("invalid_memory_subject_key")
        # 内容非空且限长，控制注入 Context 的体积。
        if not self.content.strip() or len(self.content) > 240:
            raise DomainError("invalid_memory_content")
        # 业务有效期必须带时区且区间合法。
        if self.valid_from.tzinfo is None:
            raise DomainError("memory_valid_from_requires_timezone")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None:
                raise DomainError("memory_valid_until_requires_timezone")
            if self.valid_until <= self.valid_from:
                raise DomainError("invalid_memory_validity")
        # 规范化断言值（同时完成形状校验）。
        _normalize_value(self.value)
        # 任何记忆都必须能追溯到证据。
        if not self.evidence:
            raise DomainError("memory_requires_evidence")
        # 用户明示的记忆必须至少有一条独立主证据支撑。
        if self.origin is MemoryOrigin.EXPLICIT and primary_group_count(self.evidence) < 1:
            raise DomainError("explicit_memory_requires_primary_evidence")

    @property
    def assertion_hash(self) -> str:
        """断言身份哈希：类型+主体键+规范化值，同哈希视为同一断言。"""
        payload = {
            "type": self.type.value,
            "subject_key": self.subject_key,
            "value": _normalize_value(self.value),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def confidence(self) -> float:
        """置信度：明示恒为 1；推断按独立主证据组数从 0.40 起步、封顶 0.90。"""
        if self.origin is MemoryOrigin.EXPLICIT:
            return 1.0
        groups = primary_group_count(self.evidence)
        return min(0.90, 0.40 + 0.15 * groups)

    @property
    def initial_status(self) -> SemanticMemoryStatus:
        """初始状态：明示或置信度达 0.70 直接生效，否则先作候选观察。"""
        if self.origin is MemoryOrigin.EXPLICIT or self.confidence >= 0.70:
            return SemanticMemoryStatus.ACTIVE
        return SemanticMemoryStatus.CANDIDATE

    @property
    def source_occurred_at(self) -> datetime:
        """事实发生时间：取证据中最晚发生时间（新旧替代判定的时间基准）。"""
        return max(item.source_occurred_at for item in self.evidence)


@dataclass(frozen=True)
class SemanticMemory:
    """已落库的语义记忆：一条关于用户的长期可检索事实。"""

    id: UUID
    user_id: UUID  # 归属用户
    type: SemanticMemoryType  # 记忆类型
    origin: MemoryOrigin  # 明示 / 推断
    subject_key: str  # 主体键
    value: JsonValue  # 断言值
    content: str  # 自然语言内容（检索命中后注入 Context）
    assertion_hash: str  # 断言身份哈希（同哈希=同一断言）
    confidence: float  # 置信度 0–1
    status: SemanticMemoryStatus  # 生命周期状态
    valid_from: datetime  # 业务有效期起点
    valid_until: datetime | None  # 业务有效期终点
    activated_at: datetime | None  # 激活（开始可检索）时间
    expired_at: datetime | None  # 过期时间
    source_occurred_at: datetime  # 事实发生时间（证据中最晚者）
    projector_name: str  # 产生本条目的投影器名
    projector_version: str  # 投影器版本
    embedding_model: str  # 向量化所用模型
    embedding_version: str  # 向量化模型版本
    embedding: tuple[float, ...]  # 内容向量（pgvector 检索用）
    superseded_by_id: UUID | None  # 取代者记忆 ID
    superseded_at: datetime | None  # 被取代时间
    created_at: datetime  # 落库时间
    updated_at: datetime  # 最近更新时间


def _normalize_value(value: JsonValue) -> JsonValue:
    """规范化断言值并校验形状：字符串统一小写，容器限长，非法即报错。"""
    if isinstance(value, str):
        # 字符串值：去首尾空白、转小写、压平连续空白。
        normalized = " ".join(value.strip().lower().split())
        if not normalized or len(normalized) > 160:
            raise DomainError("invalid_memory_value")
        return normalized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, tuple):
        # 元组/字典最多 8 个元素，防止记忆值无限膨胀。
        if len(value) > 8:
            raise DomainError("memory_value_too_large")
        return tuple(_normalize_scalar(item) for item in value)
    if isinstance(value, dict):
        if len(value) > 8 or any(not key or len(key) > 60 for key in value):
            raise DomainError("memory_value_too_large")
        # 键排序后逐值规范化，保证断言哈希稳定。
        return {key: _normalize_scalar(value[key]) for key in sorted(value)}
    raise DomainError("invalid_memory_value")


def _normalize_scalar(value: JsonScalar) -> JsonScalar:
    """规范化标量：字符串小写压平并限长；其余仅允许 None/bool/int/float。"""
    if isinstance(value, str):
        normalized = " ".join(value.strip().lower().split())
        if not normalized or len(normalized) > 120:
            raise DomainError("invalid_memory_value")
        return normalized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise DomainError("invalid_memory_value")
