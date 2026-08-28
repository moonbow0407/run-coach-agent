"""进程内关键词搜索：Search Index 是 Registry 的派生状态。

检索字段为 Tool name、description、tags 与 search_hint；
权重 name 最高，其次 tags、search hint、description。不引入
embedding / pgvector / Elasticsearch 或任何外部搜索服务。
"""

from dataclasses import dataclass

from app.tools.registry.definition import ToolDefinition
from app.tools.search.normalizer import extract_tokens, token_matches

# 各字段命中权重：name > tags > search_hint > description
_WEIGHT_NAME = 10
_WEIGHT_TAGS = 6
_WEIGHT_SEARCH_HINT = 4
_WEIGHT_DESCRIPTION = 2


@dataclass(frozen=True)
class ToolSearchDocument:
    """Registry 派生的搜索文档，字段与 ToolDefinition 一致。"""

    name: str
    description: str
    tags: tuple[str, ...]
    search_hint: str


@dataclass(frozen=True)
class ToolSearchHit:
    """一次搜索命中：名称、简短描述与相关性得分。"""

    name: str
    description: str
    score: int


@dataclass(frozen=True)
class _IndexedDocument:
    """加入索引时预计算的 token/文本形态，查询时无需重复规范化。"""

    document: ToolSearchDocument
    name_tokens: set[str]
    name_text: str
    description_tokens: set[str]
    description_text: str
    tags_tokens: set[str]
    tags_text: str
    hint_tokens: set[str]
    hint_text: str


class KeywordToolSearch:
    """进程内关键词搜索索引。

    add/remove 仅由 ToolRegistry 调用，索引内容与 Registry 保持同步
    （注册即入索引，注销即出索引）。
    """

    def __init__(self) -> None:
        self._documents: dict[str, _IndexedDocument] = {}

    def add(self, document: ToolSearchDocument) -> None:
        self._documents[document.name] = _IndexedDocument(
            document=document,
            name_tokens=extract_tokens(document.name),
            name_text=document.name.lower(),
            description_tokens=extract_tokens(document.description),
            description_text=document.description.lower(),
            tags_tokens=extract_tokens(" ".join(document.tags)),
            tags_text=" ".join(document.tags).lower(),
            hint_tokens=extract_tokens(document.search_hint),
            hint_text=document.search_hint.lower(),
        )

    def remove(self, name: str) -> None:
        if name not in self._documents:
            raise KeyError(f"搜索索引中不存在 Tool: {name}")
        del self._documents[name]

    def search(self, query: str) -> list[ToolSearchHit]:
        """按相关性排序返回全部命中（score > 0）。

        本方法不感知会话可见性；过滤“当前已可见 Tool”与 Top-K 截断由
        search_tools 的会话级流程完成。同分按名称字典序，保证结果确定。
        """
        tokens = extract_tokens(query)
        if not tokens:
            return []
        hits: list[ToolSearchHit] = []
        for indexed in self._documents.values():
            score = sum(
                _field_score(token, indexed) for token in tokens
            )
            if score > 0:
                hits.append(
                    ToolSearchHit(
                        name=indexed.document.name,
                        description=indexed.document.description,
                        score=score,
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.name))
        return hits


def _field_score(token: str, indexed: _IndexedDocument) -> int:
    """单个查询 token 的得分：取其命中字段的最高权重。"""
    if token_matches(token, indexed.name_tokens, indexed.name_text):
        return _WEIGHT_NAME
    if token_matches(token, indexed.tags_tokens, indexed.tags_text):
        return _WEIGHT_TAGS
    if token_matches(token, indexed.hint_tokens, indexed.hint_text):
        return _WEIGHT_SEARCH_HINT
    if token_matches(token, indexed.description_tokens, indexed.description_text):
        return _WEIGHT_DESCRIPTION
    return 0


def document_from_definition(definition: ToolDefinition) -> ToolSearchDocument:
    """从 ToolDefinition 构造搜索文档（注册时由 Registry 调用）。"""
    return ToolSearchDocument(
        name=definition.name,
        description=definition.description,
        tags=definition.tags,
        search_hint=definition.search_hint,
    )
