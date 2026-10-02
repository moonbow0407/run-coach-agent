"""Tool 定义元数据：注册、搜索与执行治理共用的描述。"""

from dataclasses import dataclass
from enum import StrEnum


class ToolRisk(StrEnum):
    """风险等级。模型 Runtime 允许 READ_ONLY / ANALYZE / DRAFT，拒绝 MUTATING。"""

    READ_ONLY = "read_only"  # 只读查询
    ANALYZE = "analyze"  # 确定性分析计算，不改数据
    DRAFT = "draft"  # 只创建草案（如调整提案），不影响生效数据
    MUTATING = "mutating"  # 直接改写数据：仅用户确认流程可执行


class ToolSource(StrEnum):
    """Tool 的提供方来源，用于区分系统级与领域级能力。"""

    SYSTEM = "system"  # 系统级工具（如 search_tools）
    COACHING = "coaching"  # Coaching 领域工具


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
