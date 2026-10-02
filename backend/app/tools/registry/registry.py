"""Tool Registry：Tool 存在性的唯一事实来源。

注册 / 注销同时维护可执行对象、元数据与搜索索引条目的生命周期；
同名注册与注销不存在的 Tool 都 fail fast，不提供静默覆盖。
Registry 是进程本地状态；多进程部署由启动时的 Provider 注册获得
相同的确定性基线。
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.common.errors import ToolRuntimeError
from app.tools.registry.definition import ToolDefinition
from app.tools.registry.protocol import AnyTool, parameters_schema_of
from app.tools.search.keyword_search import (
    KeywordToolSearch,
    document_from_definition,
)


@dataclass(frozen=True)
class RegisteredTool:
    """注册条目：可执行对象、定义、参数模型与模型可见 Schema。

    parameters_schema 在注册时由 args_model 生成，与运行时校验同源；
    Executor 校验与 Reasoner 可见 Schema 使用同一份，杜绝双协议漂移。
    """

    tool: AnyTool
    definition: ToolDefinition
    args_model: type[BaseModel]
    parameters_schema: dict[str, Any]


class ToolRegistry:
    def __init__(self, *, search: KeywordToolSearch) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._search = search

    def register(self, tool: AnyTool) -> None:
        """注册一个 Tool。同名注册立即失败，不静默覆盖。"""
        definition = tool.definition
        if definition.name in self._tools:
            raise ToolRuntimeError(f"Tool 已注册，禁止重复注册: {definition.name}")
        if self._search.contains(definition.name):
            raise ToolRuntimeError(
                f"Tool Registry 与搜索索引状态不一致: {definition.name} 仅存在于索引"
            )

        entry = RegisteredTool(
            tool=tool,
            definition=definition,
            args_model=tool.args_model,
            parameters_schema=parameters_schema_of(tool.args_model),
        )
        document = document_from_definition(definition)
        try:
            # 先更新派生索引；失败时 Registry 尚未变化，不会留下部分注册状态。
            self._search.add(document)
        except Exception as exc:
            raise ToolRuntimeError(f"Tool 搜索索引注册失败: {definition.name}") from exc
        self._tools[definition.name] = entry

    def unregister(self, name: str) -> None:
        """注销一个 Tool。注销不存在的 Tool 明确失败。

        注销后该 Tool 立即从 Resolver 与 Executor 消失（存在性归零），
        搜索索引同步移除，不会再被 search_tools 返回。
        """
        if name not in self._tools:
            raise ToolRuntimeError(f"Tool 未注册，无法注销: {name}")
        if not self._search.contains(name):
            raise ToolRuntimeError(
                f"Tool Registry 与搜索索引状态不一致: {name} 缺少索引条目"
            )

        try:
            # 先删除派生索引；失败时 executable 仍在 Registry，不产生部分注销。
            self._search.remove(name)
        except KeyError as exc:
            raise ToolRuntimeError(f"Tool 搜索索引注销失败: {name}") from exc
        del self._tools[name]

    def find(self, name: str) -> RegisteredTool | None:
        """按名称查找注册条目；不存在返回 None（存在性判断入口）。"""
        return self._tools.get(name)

    def always_on_names(self) -> frozenset[str]:
        """所有免发现即可见的工具名：Resolver 计算可见集合的基础。"""
        return frozenset(
            name
            for name, entry in self._tools.items()
            if entry.definition.always_on
        )
