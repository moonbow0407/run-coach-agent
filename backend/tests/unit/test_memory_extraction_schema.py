"""Semantic Memory extractor 的 OpenAI strict Structured Outputs 合同。"""

from collections.abc import Iterator

from app.infrastructure.memory.extraction import _extractor_schema
from app.memory.domain.semantic import SemanticMemoryType


def _nodes(value: object) -> Iterator[dict[str, object]]:
    """生成器：深度优先遍历 schema 树中的所有 dict 节点。"""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nodes(child)


def test_memory_extractor_schema_uses_openai_strict_supported_shape() -> None:
    """验证：extractor schema 严格遵守 OpenAI Structured Outputs 限制（含嵌套节点）。"""
    schema = _extractor_schema(tuple(item.value for item in SemanticMemoryType))

    # strict 模式不支持这三个上限关键字，出现即部署期会失败
    unsupported_keywords = {"maxItems", "maxLength", "maxProperties"}
    for node in _nodes(schema):
        assert unsupported_keywords.isdisjoint(node)
        if node.get("type") == "object":
            # strict 要求 additionalProperties=False 且 required 覆盖全部属性
            properties = node.get("properties")
            required = node.get("required")
            assert node.get("additionalProperties") is False
            assert isinstance(properties, dict)
            assert isinstance(required, list)
            assert set(required) == set(properties)
        if node.get("type") == "array":
            assert "items" in node
