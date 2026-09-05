"""Tool Provider：只负责装配一组 Tool，注册生命周期归 Registry。"""

from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.training_analysis_service import TrainingAnalysisService
from app.coaching.application.workout_service import WorkoutQueryService
from app.memory.application.retrieval_service import MemoryRetrievalService
from app.tools.builtin.coaching import (
    GetActiveGoalTool,
    GetActivePlanTool,
    GetLatestAthleteStateTool,
    GetRecentWorkoutsTool,
    GetUnresolvedPlanChangeTool,
    GetWorkoutDetailTool,
    GetWorkoutFeedbackTool,
)
from app.tools.builtin.memory_tools import RecallMemoriesTool
from app.tools.builtin.plan_adaptation import (
    ProposeConvertHardSessionsToEasyTool,
    ProposePlanAdaptationTool,
)
from app.tools.builtin.safety_tools import GetSafetyStatusTool
from app.tools.builtin.search_tools import SearchToolsTool
from app.tools.builtin.training_analysis import AnalyzeTrainingLoadTool, AnalyzeWorkoutTool
from app.tools.registry.protocol import AnyTool
from app.tools.resolver.resolver import ToolResolver
from app.tools.safety.gate import SafetyGate
from app.tools.search.keyword_search import KeywordToolSearch


class SystemToolProvider:
    """系统级 Tool 的唯一来源：Phase 2 只有 search_tools。"""

    def __init__(self, *, search: KeywordToolSearch, resolver: ToolResolver) -> None:
        self._search = search
        self._resolver = resolver

    def tools(self) -> list[AnyTool]:
        return [SearchToolsTool(search=self._search, resolver=self._resolver)]


class CoachingToolProvider:
    """Coaching 领域 Tool：只读查询 + 分析 + 计划调整草案。"""

    def __init__(
        self,
        *,
        workout_service: WorkoutQueryService,
        goal_service: GoalQueryService,
        plan_service: PlanQueryService,
        athlete_service: AthleteStateQueryService,
        analysis_service: TrainingAnalysisService,
        plan_adaptation_service: PlanAdaptationService,
        safety_gate: SafetyGate | None = None,
    ) -> None:
        self._workout_service = workout_service
        self._goal_service = goal_service
        self._plan_service = plan_service
        self._athlete_service = athlete_service
        self._analysis_service = analysis_service
        self._plan_adaptation_service = plan_adaptation_service
        self._safety_gate = safety_gate

    def tools(self) -> list[AnyTool]:
        # 装配只读查询、负荷分析、安全状态与计划调整草案。
        tools: list[AnyTool] = [
            GetRecentWorkoutsTool(workout_service=self._workout_service),
            GetWorkoutDetailTool(workout_service=self._workout_service),
            GetWorkoutFeedbackTool(workout_service=self._workout_service),
            GetActiveGoalTool(goal_service=self._goal_service),
            GetActivePlanTool(plan_service=self._plan_service),
            GetLatestAthleteStateTool(athlete_service=self._athlete_service),
            GetUnresolvedPlanChangeTool(plan_adaptation_service=self._plan_adaptation_service),
            AnalyzeTrainingLoadTool(analysis=self._analysis_service),
            AnalyzeWorkoutTool(analysis=self._analysis_service),
            ProposePlanAdaptationTool(adaptation=self._plan_adaptation_service),
            ProposeConvertHardSessionsToEasyTool(adaptation=self._plan_adaptation_service),
        ]
        if self._safety_gate is not None:
            tools.append(GetSafetyStatusTool(safety_gate=self._safety_gate))
        return tools


class MemoryToolProvider:
    """记忆领域 Tool：按需召回长期语义 / 情景记忆。"""

    def __init__(self, *, memory_retrieval_service: MemoryRetrievalService) -> None:
        self._memory_retrieval_service = memory_retrieval_service

    def tools(self) -> list[AnyTool]:
        return [RecallMemoriesTool(memory_retrieval_service=self._memory_retrieval_service)]
