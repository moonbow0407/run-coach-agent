from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.agent.models.message import Message


@dataclass(frozen=True)
class GoalView:
    id: UUID
    goal_type: str
    race_date: date | None
    race_distance_m: int | None
    target_time_s: int | None
    status: str


@dataclass(frozen=True)
class PlannedSessionView:
    scheduled_date: date
    session_type: str
    title: str
    prescription: dict[str, Any]


@dataclass(frozen=True)
class PlanSummary:
    id: UUID
    version: int
    starts_on: date
    ends_on: date
    status: str
    sessions: tuple[PlannedSessionView, ...]


@dataclass(frozen=True)
class AthleteStateView:
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
    goal: GoalView | None
    active_plan: PlanSummary | None
    latest_athlete_state: AthleteStateView | None
    critical_constraints: tuple[str, ...]


@dataclass(frozen=True)
class MessageView:
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class MemoryView:
    type: str
    content: str
    confidence: float | None


@dataclass(frozen=True)
class EpisodeView:
    type: str
    summary: str
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True)
class CapabilityDefinition:
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
