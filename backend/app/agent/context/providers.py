"""上下文数据源（Provider）：负责“上下文里每类信息从哪里取”。

每个 Provider 是一个 Protocol（接口）：ContextAssembler 只依赖接口，
不依赖具体实现。因此数据源未来更换实现（例如 Phase 4 把记忆检索从
空实现换成真实的语义 / 情节检索）时，装配与推理代码都不需要改动。
Phase 2 起 ContextAssembler 不再管理 Tool（CapabilityContextProvider
已删除），可见 Tool 由 Tool Runtime 的 Resolver 提供。
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.agent.context.bundle import (
    AthleteStateView,
    EpisodeView,
    GoalView,
    MemoryView,
    MessageView,
    PlanSummary,
    PlannedSessionView,
    WorkingContext,
    message_to_view,
)
from app.agent.ports.conversation_reader import ConversationReader
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import ActivePlanSummary, PlanQueryService
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.goal.models import TrainingGoal


class WorkingContextProvider(Protocol):
    async def load(self, *, user_id: UUID, as_of: datetime) -> WorkingContext:
        ...


class ConversationContextProvider(Protocol):
    async def load(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID,
        limit: int,
    ) -> list[MessageView]:
        ...


class MemoryContextProvider(Protocol):
    async def load(
        self,
        *,
        user_id: UUID,
        current_input: str,
    ) -> tuple[list[MemoryView], list[EpisodeView]]:
        ...


class DomainWorkingContextProvider:
    def __init__(
        self,
        goal_service: GoalQueryService,
        plan_service: PlanQueryService,
        athlete_service: AthleteStateQueryService,
    ) -> None:
        self._goals = goal_service
        self._plans = plan_service
        self._athlete = athlete_service

    async def load(self, *, user_id: UUID, as_of: datetime) -> WorkingContext:
        goal = await self._goals.get_active_goal(user_id=user_id)
        plan = await self._plans.get_active_plan_summary(user_id=user_id, as_of=as_of)
        state = await self._athlete.get_latest_athlete_state(user_id=user_id)
        return WorkingContext(
            goal=_goal_view(goal) if goal else None,
            active_plan=_plan_summary(plan) if plan else None,
            latest_athlete_state=_state_view(state) if state else None,
            critical_constraints=(),
        )


class SqlConversationContextProvider:
    def __init__(self, reader: ConversationReader) -> None:
        self._reader = reader

    async def load(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID,
        limit: int,
    ) -> list[MessageView]:
        messages = await self._reader.list_committed_messages(
            user_id=user_id,
            thread_id=thread_id,
            exclude_turn_id=exclude_turn_id,
            limit=limit,
        )
        return [message_to_view(message) for message in messages]


class NullMemoryContextProvider:
    """Phase 1 占位。Phase 4 替换为 Semantic/Episodic retriever，不改 Assembler。"""

    async def load(
        self,
        *,
        user_id: UUID,
        current_input: str,
    ) -> tuple[list[MemoryView], list[EpisodeView]]:
        return [], []


def _goal_view(goal: TrainingGoal) -> GoalView:
    return GoalView(
        id=goal.id,
        goal_type=goal.goal_type.value,
        race_date=goal.race_date,
        race_distance_m=goal.race_distance_m,
        target_time_s=goal.target_time_s,
        status=goal.status.value,
    )


def _plan_summary(summary: ActivePlanSummary) -> PlanSummary:
    return PlanSummary(
        id=summary.plan.id,
        version=summary.plan.version,
        starts_on=summary.plan.starts_on,
        ends_on=summary.plan.ends_on,
        status=summary.plan.status.value,
        sessions=tuple(
            PlannedSessionView(
                scheduled_date=session.scheduled_date,
                session_type=session.session_type.value,
                title=session.title,
                prescription=session.prescription,
            )
            for session in summary.sessions
        ),
        window_start=summary.window_start,
        window_end=summary.window_end,
        truncated=summary.truncated,
    )


def _state_view(snapshot: AthleteStateSnapshot) -> AthleteStateView:
    return AthleteStateView(
        version=snapshot.version,
        as_of=snapshot.as_of,
        fatigue_level=snapshot.fatigue_level.value if snapshot.fatigue_level else None,
        recovery_level=snapshot.recovery_level.value if snapshot.recovery_level else None,
        recent_training_load=snapshot.recent_training_load,
        workout_completion_rate=snapshot.workout_completion_rate,
        confidence=snapshot.confidence,
        algorithm_version=snapshot.algorithm_version,
    )
