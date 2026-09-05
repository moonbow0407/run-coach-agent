"""get_workout_feedback 仍需 discovery；近期反馈改由 WorkingContext 注入。"""

from app.tools.builtin.coaching import GetWorkoutFeedbackTool


class _Unused:
    pass


def test_get_workout_feedback_remains_searchable_not_always_on() -> None:
    """验证：单课反馈工具不 always-on，避免扩大初始 Schema；摘要走热上下文。"""
    tool = GetWorkoutFeedbackTool(workout_service=_Unused())  # type: ignore[arg-type]
    assert tool.definition.always_on is False
    assert tool.definition.name == "get_workout_feedback"
