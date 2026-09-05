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
    FeedbackSummaryView,
    GoalView,
    MemoryContextResult,
    MessageView,
    PlannedSessionView,
    PlanSummary,
    WorkingContext,
    message_to_view,
)
from app.agent.ports.conversation_reader import ConversationReader
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import ActivePlanSummary, PlanQueryService
from app.coaching.application.workout_service import FeedbackSummary, WorkoutQueryService
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.domain.goal.models import TrainingGoal


# 三个 Provider Protocol：只约束方法签名，实现方无需显式继承
class WorkingContextProvider(Protocol):
    """热上下文数据源接口：当前目标 / 生效计划 / 最新跑者状态。"""

    async def load(self, *, user_id: UUID, as_of: datetime) -> WorkingContext: ...


class ConversationContextProvider(Protocol):
    """历史对话数据源接口：本线程已提交 Turn 的消息（排除当前轮）。"""

    async def load(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID,
        limit: int,
    ) -> list[MessageView]: ...


class MemoryContextProvider(Protocol):
    """长期记忆数据源接口：返回带检索元数据的结构化结果。"""

    async def load(
        self,
        *,
        user_id: UUID,
        current_input: str,
        as_of: datetime,
    ) -> MemoryContextResult: ...


class DomainWorkingContextProvider:
    """生产实现：调用 coaching 域的查询服务组装热上下文。"""

    def __init__(
        self,
        goal_service: GoalQueryService,
        plan_service: PlanQueryService,
        athlete_service: AthleteStateQueryService,
        workout_service: WorkoutQueryService,
    ) -> None:
        self._goals = goal_service
        self._plans = plan_service
        self._athlete = athlete_service
        self._workouts = workout_service  # 近期反馈摘要，减少搜工具跳转

    async def load(self, *, user_id: UUID, as_of: datetime) -> WorkingContext:
        # 目标 / 计划 / 状态 / 近期反馈独立查询：新用户可能部分缺失
        goal = await self._goals.get_active_goal(user_id=user_id)
        plan = await self._plans.get_active_plan_summary(user_id=user_id, as_of=as_of)
        state = await self._athlete.get_latest_athlete_state(user_id=user_id)
        feedback = await self._workouts.list_recent_feedback_summaries(user_id=user_id)
        return WorkingContext(
            goal=_goal_view(goal) if goal else None,
            active_plan=_plan_summary(plan) if plan else None,
            latest_athlete_state=_state_view(state) if state else None,
            recent_feedback=tuple(_feedback_view(item) for item in feedback),
            critical_constraints=(),
        )


class SqlConversationContextProvider:
    """生产实现：通过 ConversationReader 读取已提交历史消息。"""

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
    """窄测试替身；生产装配禁止使用。"""

    async def load(
        self,
        *,
        user_id: UUID,
        current_input: str,
        as_of: datetime,
    ) -> MemoryContextResult:
        return MemoryContextResult((), (), "null", False, False)


def _goal_view(goal: TrainingGoal) -> GoalView:
    """领域对象 → 上下文视图的字段映射。"""
    return GoalView(
        id=goal.id,
        goal_type=goal.goal_type.value,
        race_date=goal.race_date,
        race_distance_m=goal.race_distance_m,
        target_time_s=goal.target_time_s,
        status=goal.status.value,
    )


def _plan_summary(summary: ActivePlanSummary) -> PlanSummary:
    """计划领域摘要 → 上下文计划摘要视图。"""
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
    """跑者状态快照 → 上下文状态视图。"""
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


def _feedback_view(summary: FeedbackSummary) -> FeedbackSummaryView:
    """反馈摘要领域对象 → 上下文视图。"""
    return FeedbackSummaryView(
        workout_id=summary.workout_id,
        started_on=summary.started_on,
        perceived_exertion=summary.perceived_exertion,
        subjective_fatigue=summary.subjective_fatigue,
        note_snippet=summary.note_snippet,
    )
