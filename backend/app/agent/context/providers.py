from typing import Protocol
from uuid import UUID

from app.agent.context.bundle import (
    AthleteStateView,
    CapabilityDefinition,
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
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.goal.models import TrainingGoal
from app.coaching.domain.plan.models import ActivePlan


class WorkingContextProvider(Protocol):
    async def load(self, *, user_id: UUID) -> WorkingContext:
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


class CapabilityContextProvider(Protocol):
    async def load(self) -> list[CapabilityDefinition]:
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

    async def load(self, *, user_id: UUID) -> WorkingContext:
        goal = await self._goals.get_active_goal(user_id=user_id)
        plan = await self._plans.get_active_plan(user_id=user_id)
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


PHASE1_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        name="get_recent_workouts",
        description="读取该用户最近若干天的训练记录。",
        arguments_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365}},
            "required": ["days"],
        },
    ),
    CapabilityDefinition(
        name="get_active_goal",
        description="读取该用户当前生效的训练目标。",
        arguments_schema={"type": "object", "properties": {}},
    ),
    CapabilityDefinition(
        name="get_active_plan",
        description="读取该用户当前生效的训练计划及课次。",
        arguments_schema={"type": "object", "properties": {}},
    ),
    CapabilityDefinition(
        name="get_latest_athlete_state",
        description="读取该用户最近一份 AthleteStateSnapshot。这是已有快照，不是现场计算。",
        arguments_schema={"type": "object", "properties": {}},
    ),
)


class StaticCapabilityContextProvider:
    async def load(self) -> list[CapabilityDefinition]:
        return list(PHASE1_CAPABILITIES)


def _goal_view(goal: TrainingGoal) -> GoalView:
    return GoalView(
        id=goal.id,
        goal_type=goal.goal_type.value,
        race_date=goal.race_date,
        race_distance_m=goal.race_distance_m,
        target_time_s=goal.target_time_s,
        status=goal.status.value,
    )


def _plan_summary(active: ActivePlan) -> PlanSummary:
    return PlanSummary(
        id=active.plan.id,
        version=active.plan.version,
        starts_on=active.plan.starts_on,
        ends_on=active.plan.ends_on,
        status=active.plan.status.value,
        sessions=tuple(
            PlannedSessionView(
                scheduled_date=session.scheduled_date,
                session_type=session.session_type.value,
                title=session.title,
                prescription=session.prescription,
            )
            for session in active.sessions
        ),
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
