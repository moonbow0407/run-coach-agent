"""计划调整确认 API 的请求 / 响应模型。"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_session_id: UUID
    scheduled_date: date
    from_type: str
    to_type: str
    old_title: str
    new_title: str
    old_prescription: dict[str, Any]
    new_prescription: dict[str, Any]


class PlanChangePayloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_days: int
    changes: list[SessionChangeResponse]


class PlanChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_id: UUID
    from_plan_id: UUID
    from_plan_version: int
    based_on_state_id: UUID
    based_on_state_version: int
    source_turn_id: UUID | None
    source_run_id: UUID | None
    as_of: datetime
    change_type: str
    payload: PlanChangePayloadResponse
    reason: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resulting_plan_id: UUID | None


class PlannedSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    scheduled_date: date
    session_type: str
    title: str
    prescription: dict[str, Any]


class ResultingPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    status: str
    starts_on: date
    ends_on: date
    goal_id: UUID | None
    sessions: list[PlannedSessionResponse] = Field(default_factory=list)


class ConfirmPlanChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_change: PlanChangeResponse
    resulting_plan_id: UUID | None
    resulting_plan: ResultingPlanResponse | None = None
