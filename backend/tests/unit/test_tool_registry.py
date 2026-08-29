"""Registry 不变量：存在性唯一事实来源、同名 fail fast、注销失效、索引同步。"""

import pytest

from app.common.errors import ToolRuntimeError
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource
from app.tools.registry.protocol import parameters_schema_of
from app.tools.registry.registry import ToolRegistry
from app.tools.search.keyword_search import KeywordToolSearch
from tests.unit.tool_helpers import SampleArgs, SampleTool


def _registry() -> tuple[ToolRegistry, KeywordToolSearch]:
    search = KeywordToolSearch()
    return ToolRegistry(search=search), search


def test_register_and_find() -> None:
    registry, _ = _registry()
    registry.register(SampleTool("alpha", always_on=True))
    entry = registry.find("alpha")
    assert entry is not None
    assert entry.definition.name == "alpha"
    assert entry.args_model is SampleArgs
    # 模型可见 Schema 与运行时校验同源（同一参数模型生成）。
    assert entry.parameters_schema == parameters_schema_of(SampleArgs)


def test_duplicate_registration_fails_fast() -> None:
    registry, _ = _registry()
    registry.register(SampleTool("alpha"))
    with pytest.raises(ToolRuntimeError, match="已注册"):
        registry.register(SampleTool("alpha"))


def test_unregister_unknown_tool_fails() -> None:
    registry, _ = _registry()
    with pytest.raises(ToolRuntimeError, match="未注册"):
        registry.unregister("missing")


def test_unregister_removes_from_search_index() -> None:
    registry, search = _registry()
    registry.register(SampleTool("alpha"))
    assert any(hit.name == "alpha" for hit in search.search("alpha"))
    registry.unregister("alpha")
    assert registry.find("alpha") is None
    assert search.search("alpha") == []


def test_register_index_failure_keeps_registry_unchanged(monkeypatch) -> None:
    registry, search = _registry()

    def fail_to_add(_document) -> None:
        raise RuntimeError("index failure")

    monkeypatch.setattr(search, "add", fail_to_add)
    with pytest.raises(ToolRuntimeError, match="索引注册失败"):
        registry.register(SampleTool("alpha"))
    assert registry.find("alpha") is None


def test_unregister_detects_missing_index_before_mutation() -> None:
    registry, search = _registry()
    registry.register(SampleTool("alpha"))
    search.remove("alpha")

    with pytest.raises(ToolRuntimeError, match="状态不一致"):
        registry.unregister("alpha")
    assert registry.find("alpha") is not None


def test_always_on_names_track_registered_tools() -> None:
    registry, _ = _registry()
    registry.register(SampleTool("always", always_on=True))
    registry.register(SampleTool("hidden", always_on=False))
    assert registry.always_on_names() == {"always"}
    registry.unregister("always")
    assert registry.always_on_names() == set()


def _definition_kwargs() -> dict:
    return {
        "name": "alpha",
        "description": "alpha tool",
        "tags": ("alpha",),
        "search_hint": "alpha hint",
        "always_on": True,
        "risk": ToolRisk.READ_ONLY,
        "source": ToolSource.SYSTEM,
        "timeout_s": 1.0,
    }


def test_definition_metadata_roundtrip() -> None:
    # ToolDefinition 是 frozen dataclass，元数据完整保存。
    definition = ToolDefinition(**_definition_kwargs())
    assert definition.risk is ToolRisk.READ_ONLY
    assert definition.source is ToolSource.SYSTEM
    assert definition.timeout_s == 1.0
