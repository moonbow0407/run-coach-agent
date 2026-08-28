"""关键词搜索：中文查询、Tool name / tags / search hint 权重与 Top-K 边界。"""

from app.tools.search.keyword_search import (
    KeywordToolSearch,
    ToolSearchDocument,
)


def _doc(name: str, description: str = "", tags: tuple[str, ...] = (), hint: str = "") -> ToolSearchDocument:
    return ToolSearchDocument(name=name, description=description, tags=tags, search_hint=hint)


def test_chinese_query_matches_hint_and_tags() -> None:
    search = KeywordToolSearch()
    search.add(
        _doc(
            "get_workout_feedback",
            "读取训练反馈",
            ("feedback", "反馈"),
            "读取训练后的主观感受与疲劳",
        )
    )
    search.add(_doc("get_active_plan", "读取训练计划", ("plan",), "读取课表"))
    hits = search.search("主观疲劳")
    assert [hit.name for hit in hits] == ["get_workout_feedback"]


def test_tool_name_ranks_highest() -> None:
    search = KeywordToolSearch()
    search.add(_doc("get_workout_detail", tags=("plan",)))
    search.add(_doc("get_active_plan", tags=("workout",)))
    # 两个文档都同时含对方关键词，但各自 name 精确命中自己的查询 token。
    hits = search.search("get_workout_detail")
    assert hits[0].name == "get_workout_detail"


def test_tags_rank_over_description() -> None:
    search = KeywordToolSearch()
    search.add(_doc("alpha", description="workout planner"))
    search.add(_doc("beta", tags=("workout",)))
    hits = search.search("workout")
    assert hits[0].name == "beta"


def test_search_hint_ranks_over_description() -> None:
    search = KeywordToolSearch()
    search.add(_doc("alpha", description="fatigue analyzer"))
    search.add(_doc("beta", hint="fatigue snapshot"))
    hits = search.search("fatigue")
    assert hits[0].name == "beta"


def test_no_match_returns_empty() -> None:
    search = KeywordToolSearch()
    search.add(_doc("get_active_plan"))
    assert search.search("完全不相关xyz") == []


def test_snake_case_name_tokenized() -> None:
    search = KeywordToolSearch()
    search.add(_doc("get_workout_detail"))
    hits = search.search("workout detail")
    assert [hit.name for hit in hits] == ["get_workout_detail"]


def test_single_cjk_char_substring_match() -> None:
    search = KeywordToolSearch()
    search.add(_doc("tool_a", description="疲劳恢复"))
    hits = search.search("疲")
    assert [hit.name for hit in hits] == ["tool_a"]
