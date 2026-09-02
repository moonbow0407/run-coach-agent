"""Resolver：每轮重算当前可见 Tool（Registered ≠ Visible ≠ Executable）。

可见集合 = 仍注册的 always-on Tool ∪ 仍注册且已发现的 Tool。
Registry 是存在性的唯一事实来源：已发现但随后注销的 Tool 在这里
立即消失。
"""

from dataclasses import dataclass
from typing import Any

from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.session import ToolSession


@dataclass(frozen=True)
class VisibleTool:
    """当前 Reasoner 可见的 Tool（native tool calling 的 schema 形态）。

    parameters_schema 来自注册时由参数模型生成的同一份 Schema。
    """

    name: str  # 工具名
    description: str  # 面向模型的用途描述
    parameters_schema: dict[str, Any]  # 模型可见参数 Schema


class ToolResolver:
    """每轮根据会话与 Registry 计算可见工具集；自身无跨轮状态。"""

    def __init__(self, *, registry: ToolRegistry) -> None:
        self._registry = registry  # 存在性唯一事实来源：已注销工具立即不可见

    def visible_names(self, session: ToolSession) -> frozenset[str]:
        """当前可见名称集合：always-on ∪ 已发现，均要求仍在 Registry 中。"""
        names = set(self._registry.always_on_names())
        names.update(
            name
            for name in session.discovered_names()
            if self._registry.find(name) is not None
        )
        return frozenset(names)

    def is_visible(self, session: ToolSession, name: str) -> bool:
        """判断工具对当前会话是否可见（Executor 执行前的门槛之一）。"""
        return name in self.visible_names(session)

    def visible_tools(self, session: ToolSession) -> list[VisibleTool]:
        """按名称排序的可见 Tool 定义，保证每轮传给模型的内容确定。"""
        tools: list[VisibleTool] = []
        for name in sorted(self.visible_names(session)):
            entry = self._registry.find(name)
            if entry is None:
                # visible_names 已过滤未注册 Tool；到这里说明 Registry 状态损坏。
                raise RuntimeError(f"可见集合中的 Tool 不在 Registry: {name}")
            tools.append(
                VisibleTool(
                    name=name,
                    description=entry.definition.description,
                    parameters_schema=entry.parameters_schema,
                )
            )
        return tools
