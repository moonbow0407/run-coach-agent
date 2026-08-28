"""上下文相关数据结构。

ContextBundle 是发给 Reasoner 的完整上下文合同；各 *View 是领域对象
在上下文中的只读投影（只含 Prompt 需要的字段，不含 ORM 与业务方法）。
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.agent.models.message import Message


@dataclass(frozen=True)
class GoalView:
    """当前训练目标在上下文中的视图。"""

    id: UUID
    goal_type: str
    race_date: date | None
    race_distance_m: int | None
    target_time_s: int | None
    status: str


@dataclass(frozen=True)
class PlannedSessionView:
    """计划中的单次课次：日期 + 类型 + 标题 + 结构化处方（距离 / 配速等）。"""

    scheduled_date: date
    session_type: str
    title: str
    prescription: dict[str, Any]


@dataclass(frozen=True)
class PlanSummary:
    """当前生效训练计划摘要及其课次列表。"""

    id: UUID
    version: int
    starts_on: date
    ends_on: date
    status: str
    sessions: tuple[PlannedSessionView, ...]


@dataclass(frozen=True)
class AthleteStateView:
    """最新跑者状态快照视图。

    这是系统推导状态（含版本与 as_of），不是用户口头报告的主观感受。
    """

    version: int
    as_of: datetime
    fatigue_level: str | None
    recovery_level: str | None
    recent_training_load: float | None
    workout_completion_rate: float | None
    confidence: float | None
    algorithm_version: str


@dataclass(frozen=True)
class WorkingContext:
    """本次运行的热上下文：目标 + 计划 + 最新状态 + 关键约束。

    不独立拥有数据、不做长期存储，只反映“现在”的高频信息。
    """

    goal: GoalView | None
    active_plan: PlanSummary | None
    latest_athlete_state: AthleteStateView | None
    critical_constraints: tuple[str, ...]


@dataclass(frozen=True)
class MessageView:
    """历史消息视图：只保留角色、内容与时间。"""

    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class MemoryView:
    """语义记忆视图：用户的长期特征。Phase 1 恒为空。"""

    type: str
    content: str
    confidence: float | None


@dataclass(frozen=True)
class EpisodeView:
    """情节记忆视图：历史相似经历。Phase 1 恒为空。"""

    type: str
    summary: str
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True)
class CapabilityDefinition:
    """一个可调用能力的描述：名称、说明与参数 JSON Schema，供模型决定是否调用。"""

    name: str
    description: str
    arguments_schema: dict[str, Any]


@dataclass(frozen=True)
class ContextBundle:
    """发给 Reasoner 的完整上下文合同。

    Phase 1 中 semantic/episodic memories 为空，但字段从第一版就保留，
    以便 Phase 4 替换 MemoryContextProvider 时不改 Reasoner API。
    """

    system: str
    working_context: WorkingContext
    recent_messages: list[MessageView]
    semantic_memories: list[MemoryView]
    episodic_memories: list[EpisodeView]
    capabilities: list[CapabilityDefinition]
    current_input: str


@dataclass(frozen=True)
class ContextAssemblyRequest:
    user_id: UUID
    thread_id: UUID
    turn_id: UUID
    current_input: str


def message_to_view(message: Message) -> MessageView:
    return MessageView(
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
    )
