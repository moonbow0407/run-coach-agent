"""Tool Provider：只负责装配一组 Tool，注册生命周期归 Registry。

Phase 2 仅实现 System Provider（search_tools）与 Coaching Provider
（六个 read-only 领域工具），不引入 Provider Manager 或数据库 Catalog。
"""

from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.workout_service import WorkoutQueryService
from app.tools.builtin.coaching import (
    GetActiveGoalTool,
    GetActivePlanTool,
    GetLatestAthleteStateTool,
    GetRecentWorkoutsTool,
    GetWorkoutDetailTool,
    GetWorkoutFeedbackTool,
)
from app.tools.builtin.search_tools import SearchToolsTool
from app.tools.registry.protocol import AnyTool
from app.tools.resolver.resolver import ToolResolver
from app.tools.search.keyword_search import KeywordToolSearch


class SystemToolProvider:
    """系统级 Tool 的唯一来源：Phase 2 只有 search_tools。"""

    def __init__(self, *, search: KeywordToolSearch, resolver: ToolResolver) -> None:
        self._search = search
        self._resolver = resolver

    def tools(self) -> list[AnyTool]:
        return [SearchToolsTool(search=self._search, resolver=self._resolver)]


class CoachingToolProvider:
    """Coaching 领域的六个 read-only Tool。"""

    def __init__(
        self,
        *,
        workout_service: WorkoutQueryService,
        goal_service: GoalQueryService,
        plan_service: PlanQueryService,
        athlete_service: AthleteStateQueryService,
    ) -> None:
        self._workout_service = workout_service
        self._goal_service = goal_service
        self._plan_service = plan_service
        self._athlete_service = athlete_service

    def tools(self) -> list[AnyTool]:
        return [
            GetRecentWorkoutsTool(workout_service=self._workout_service),
            GetWorkoutDetailTool(workout_service=self._workout_service),
            GetWorkoutFeedbackTool(workout_service=self._workout_service),
            GetActiveGoalTool(goal_service=self._goal_service),
            GetActivePlanTool(plan_service=self._plan_service),
            GetLatestAthleteStateTool(athlete_service=self._athlete_service),
        ]
