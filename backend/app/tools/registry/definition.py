"""Tool 定义元数据：注册、搜索与执行治理共用的描述。"""

from dataclasses import dataclass
from enum import StrEnum


class ToolRisk(StrEnum):
    """风险等级。Phase 2 只提供并执行 read_only；mutating 保留语义但不落地。"""

    READ_ONLY = "read_only"
    MUTATING = "mutating"


class ToolSource(StrEnum):
    """Tool 的提供方来源，用于区分系统级与领域级能力。"""

    SYSTEM = "system"
    COACHING = "coaching"


@dataclass(frozen=True)
class ToolDefinition:
    """一个 Tool 的完整元数据。

    name 是唯一标识；description 面向模型说明用途；tags 与 search_hint
    服务关键词搜索（name 权重最高，其次 tags、search_hint、description）。
    always_on 表示无需 search_tools 发现即可见；timeout_s 由 Executor
    统一执行超时控制。
    """

    name: str
    description: str
    tags: tuple[str, ...]
    search_hint: str
    always_on: bool
    risk: ToolRisk
    source: ToolSource
    timeout_s: float
