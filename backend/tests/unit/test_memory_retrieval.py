"""记忆检索的上下文预算裁剪（_bounded）：整条丢弃、条数硬顶。"""

from app.memory.application.retrieval_service import _bounded


def test_context_budget_drops_ranked_tail_without_fragmenting_items() -> None:
    """验证：超出字符预算时按排名整条丢弃尾部，绝不截断单条记忆文本。"""
    items = tuple(f"{index}:" + "x" * 238 for index in range(8))

    selected, truncated = _bounded(
        items,
        limit=8,
        budget=1600,
        text=lambda item: item,
    )

    assert selected == items[:6]
    assert all(item in items for item in selected)
    # truncated 标记提示上游「还有内容被裁掉」
    assert truncated


def test_count_limit_is_a_hard_cap_even_when_text_budget_has_room() -> None:
    """验证：条数上限是硬顶——预算再宽裕也不多发。"""
    items = ("a", "b", "c")

    selected, truncated = _bounded(
        items,
        limit=2,
        budget=100,
        text=lambda item: item,
    )

    assert selected == ("a", "b")
    assert truncated
