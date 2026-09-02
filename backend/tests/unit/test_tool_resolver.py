"""Resolver 三态语义：Registered ≠ Visible ≠ Executable。"""

from uuid import uuid4

from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.resolver import ToolResolver
from app.tools.search.keyword_search import KeywordToolSearch
from tests.unit.tool_helpers import SampleTool


def _setup() -> tuple[ToolRegistry, ToolResolver]:
    """注册一个常驻（always-on）与一个默认隐藏的工具，返回 registry 与 resolver。"""
    search = KeywordToolSearch()
    registry = ToolRegistry(search=search)
    registry.register(SampleTool("always_on_tool", always_on=True))
    registry.register(SampleTool("hidden_tool"))
    return registry, ToolResolver(registry=registry)


def test_initial_visible_set_is_always_on_only() -> None:
    """验证：会话初始可见集只含 always-on 工具，其余对模型隐藏。"""
    registry, resolver = _setup()
    session = resolver_visible_session(registry)
    assert resolver.visible_names(session) == {"always_on_tool"}
    assert not resolver.is_visible(session, "hidden_tool")


def test_discovery_extends_visible_set() -> None:
    """验证：发现（unlock）把隐藏工具扩入本会话可见集。"""
    registry, resolver = _setup()
    session = resolver_visible_session(registry)
    added = session.unlock(["hidden_tool"])
    assert added == {"hidden_tool"}
    assert resolver.visible_names(session) == {"always_on_tool", "hidden_tool"}


def test_unregister_removes_discovered_tool_immediately() -> None:
    """验证：工具注销后立即从已发现可见集消失。"""
    registry, resolver = _setup()
    session = resolver_visible_session(registry)
    session.unlock(["hidden_tool"])
    registry.unregister("hidden_tool")
    # 已发现但注销的 Tool 立即从 Resolver 消失。
    assert resolver.visible_names(session) == {"always_on_tool"}


def test_unlock_filters_unregistered_names() -> None:
    """验证：unlock 静默过滤未注册名字，只返回实际新增的部分。"""
    registry, _resolver = _setup()
    session = resolver_visible_session(registry)
    added = session.unlock(["hidden_tool", "not_registered"])
    assert added == {"hidden_tool"}


def test_unlock_deduplicates_existing_names() -> None:
    """验证：重复 unlock 幂等——已可见的名字不再计入新增。"""
    registry, resolver = _setup()
    session = resolver_visible_session(registry)
    assert session.unlock(["hidden_tool"]) == {"hidden_tool"}
    assert session.unlock(["hidden_tool"]) == set()
    assert resolver.visible_names(session) == {"always_on_tool", "hidden_tool"}


def test_run_local_isolation_between_sessions() -> None:
    # Discovery 只属于一个 ToolSession；新 Run 的会话不继承上一个 Run 的发现。
    registry, resolver = _setup()
    first = resolver_visible_session(registry)
    first.unlock(["hidden_tool"])
    second = resolver_visible_session(registry)
    assert resolver.visible_names(second) == {"always_on_tool"}


def test_visible_tools_sorted_and_schema_present() -> None:
    """验证：可见工具按名稳定排序，且都带描述与对象 Schema（供模型调用）。"""
    registry, resolver = _setup()
    session = resolver_visible_session(registry)
    session.unlock(["hidden_tool"])
    tools = resolver.visible_tools(session)
    assert [tool.name for tool in tools] == ["always_on_tool", "hidden_tool"]
    for tool in tools:
        assert tool.description
        assert tool.parameters_schema["type"] == "object"


def resolver_visible_session(registry: ToolRegistry):
    """为一次 Run 构造新的可见性会话（函数内 import 以避免循环依赖）。"""
    from app.tools.resolver.session import ToolSession

    return ToolSession(run_id=uuid4(), registry=registry)
