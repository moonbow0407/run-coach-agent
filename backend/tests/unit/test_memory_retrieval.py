from app.memory.application.retrieval_service import _bounded


def test_context_budget_drops_ranked_tail_without_fragmenting_items() -> None:
    items = tuple(f"{index}:" + "x" * 238 for index in range(8))

    selected, truncated = _bounded(
        items,
        limit=8,
        budget=1600,
        text=lambda item: item,
    )

    assert selected == items[:6]
    assert all(item in items for item in selected)
    assert truncated


def test_count_limit_is_a_hard_cap_even_when_text_budget_has_room() -> None:
    items = ("a", "b", "c")

    selected, truncated = _bounded(
        items,
        limit=2,
        budget=100,
        text=lambda item: item,
    )

    assert selected == ("a", "b")
    assert truncated
