"""ToolSession：每个 AgentRun 一个的 Tool 会话。

持有 run_id 与 Run-local Discovery 状态。Discovery 更新（注册再确认 +
写入解锁集合）在 unlock 内一次完成，保证与 search_tools 报告的命中
集合一致。
"""

from typing import TYPE_CHECKING
from uuid import UUID

from app.tools.resolver.discovery import ToolDiscoveryState

if TYPE_CHECKING:
    # 仅供类型标注使用，避免 session -> registry -> protocol -> session 的运行时循环导入。
    from app.tools.registry.registry import ToolRegistry


class ToolSession:
    def __init__(self, *, run_id: UUID, registry: "ToolRegistry") -> None:
        self._run_id = run_id
        self._registry = registry
        self._discovery = ToolDiscoveryState()

    @property
    def run_id(self) -> UUID:
        return self._run_id

    def discovered_names(self) -> frozenset[str]:
        return self._discovery.names()

    def unlock(self, names: list[str] | frozenset[str] | set[str]) -> frozenset[str]:
        """Registry 再确认后加入 Discovery，返回实际加入的集合。

        只有仍存在于 Registry 的名称才会被解锁；返回值即 search_tools
        可以向模型报告的命中集合，二者必须完全一致。
        """
        confirmed = [name for name in names if self._registry.find(name) is not None]
        return self._discovery.add(confirmed)
