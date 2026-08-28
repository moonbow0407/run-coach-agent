"""上下文数据源（Provider）：负责“上下文里每类信息从哪里取”。

每个 Provider 是一个 Protocol（接口）：ContextAssembler 只依赖接口，
不依赖具体实现。因此数据源未来更换实现（例如 Phase 4 把记忆检索从
空实现换成真实的语义 / 情节检索）时，装配与推理代码都不需要改动。
"""

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
    """提供本次运行的热上下文：当前目标 / 生效计划 / 最新跑者状态。"""

    async def load(self, *, user_id: UUID) -> WorkingContext:
        ...


class ConversationContextProvider(Protocol):
    """提供本线程中已提交 Turn 的历史消息（排除当前 Turn）。"""

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
    """提供长期记忆（语义记忆 + 情节记忆）。Phase 1 实现返回空列表。"""

    async def load(
        self,
        *,
        user_id: UUID,
        current_input: str,
    ) -> tuple[list[MemoryView], list[EpisodeView]]:
        ...


class CapabilityContextProvider(Protocol):
    """提供可调用能力清单，供模型在推理时选择工具。"""

    async def load(self) -> list[CapabilityDefinition]:
        ...


class DomainWorkingContextProvider:
    """从 coaching 领域查询服务读取热上下文（目标 / 计划 / 状态快照）。"""

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
    """从数据库读取已提交的历史消息，并转成只含 role / content 的视图。"""

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


# Phase 1 静态能力清单：与 SimpleCapabilityExecutor 支持的能力一一对应。
# Phase 2 将由 Tool Registry 动态生成，替换本常量与 StaticCapabilityContextProvider。
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
    """原样返回静态能力清单。"""

    async def load(self) -> list[CapabilityDefinition]:
        return list(PHASE1_CAPABILITIES)


# 以下三个转换函数：领域对象 → 上下文视图。
# 只保留 Prompt 需要的字段，避免领域模型内部结构泄漏进模型上下文。


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
