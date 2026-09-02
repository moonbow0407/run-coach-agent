"""Run-local Discovery：仅当前 AgentRun 内有效的解锁记录。

只保存当前 Run 通过 search_tools 获得的 Tool 名称，不写 PostgreSQL、
Redis 或 Message，也不跨 Turn 复用；AgentRun 结束随 ToolSession 销毁。
"""


class ToolDiscoveryState:
    """Run 内已解锁工具名的内存集合：随 ToolSession 创建与销毁。"""

    def __init__(self) -> None:
        self._names: set[str] = set()  # 已解锁（经 search_tools 发现）的工具名

    def names(self) -> frozenset[str]:
        """当前已解锁名称的只读视图。"""
        return frozenset(self._names)

    def add(self, names: frozenset[str] | set[str] | list[str]) -> frozenset[str]:
        """加入新名称，返回实际新增集合（重复名称不再计入）。"""
        added = frozenset(name for name in names if name not in self._names)
        self._names.update(added)
        return added
