"""上下文相关数据结构。

ContextBundle 是发给 Reasoner 的完整上下文合同；各 *View 是领域对象
在上下文中的只读投影（只含 Prompt 需要的字段，不含 ORM 与业务方法）。
Phase 2 起 ContextBundle 不再携带任何 Tool 定义：可见 Tool 由
ReasoningContext.visible_tools 每轮单独提供。
"""

from dataclasses import dataclass
from datetime import date, datetime
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
    """计划课次在上下文中的视图。"""

    scheduled_date: date
    session_type: str
    title: str
    prescription: dict[str, object]


@dataclass(frozen=True)
class PlanSummary:
    """受 Tool Result Budget 约束的计划摘要视图。

    与 get_active_plan Tool 共用同一摘要语义：sessions 只覆盖
    [window_start, window_end]（当前 ISO 周 ∪ 未来 14 天）且不超过
    20 条；truncated 表示超出上限被显式截断。ContextBundle 不携带
    完整长期计划。
    """

    id: UUID
    version: int
    starts_on: date
    ends_on: date
    status: str
    sessions: tuple[PlannedSessionView, ...]
    window_start: date
    window_end: date
    truncated: bool


@dataclass(frozen=True)
class AthleteStateView:
    """最新跑者状态快照在上下文中的视图（已有快照，不是现场计算）。"""

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
    """热上下文：跑者现在怎么样的当前结论。"""

    goal: GoalView | None
    active_plan: PlanSummary | None
    latest_athlete_state: AthleteStateView | None
    critical_constraints: tuple[str, ...]


@dataclass(frozen=True)
class MessageView:
    """历史 committed 消息在上下文中的视图。"""

    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class MemoryView:
    """语义记忆的精简视图，不携带 embedding 或 Evidence graph。"""

    id: UUID
    type: str
    content: str
    origin: str
    confidence: float
    valid_from: datetime
    valid_until: datetime | None


@dataclass(frozen=True)
class EpisodeView:
    """已完成情节记忆的精简视图。"""

    id: UUID
    type: str
    summary: str
    started_at: datetime
    ended_at: datetime
    importance: float


@dataclass(frozen=True)
class ContextBundle:
    """发给 Reasoner 的完整上下文合同。

    semantic/episodic memories 由受预算约束的真实检索 Provider 提供。
    """

    system: str
    working_context: WorkingContext
    recent_messages: list[MessageView]
    semantic_memories: list[MemoryView]
    episodic_memories: list[EpisodeView]
    current_input: str


@dataclass(frozen=True)
class ContextAssemblyRequest:
    """一次上下文装配请求。timestamp 是本次请求的可信时间基准。"""

    user_id: UUID
    thread_id: UUID
    turn_id: UUID
    timestamp: datetime
    current_input: str


def message_to_view(message: Message) -> MessageView:
    return MessageView(
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
    )
