"""计划调整确认 API 的请求 / 响应模型。"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.coaching.domain.plan.models import PlanChange
from app.coaching.ports.plan_activation_store import PlanActivationResult


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


def to_plan_change_response(change: PlanChange) -> PlanChangeResponse:
    """领域 PlanChange → 传输 DTO 的唯一映射，查询与确认 / 拒绝共用。"""
    return PlanChangeResponse(
        id=change.id,
        user_id=change.user_id,
        from_plan_id=change.from_plan_id,
        from_plan_version=change.from_plan_version,
        based_on_state_id=change.based_on_state_id,
        based_on_state_version=change.based_on_state_version,
        source_turn_id=change.source_turn_id,
        source_run_id=change.source_run_id,
        as_of=change.as_of,
        change_type=change.change_type.value,
        payload=PlanChangePayloadResponse(
            horizon_days=change.payload.horizon_days,
            changes=[
                SessionChangeResponse(
                    source_session_id=item.source_session_id,
                    scheduled_date=item.scheduled_date,
                    from_type=item.from_type.value,
                    to_type=item.to_type.value,
                    old_title=item.old_title,
                    new_title=item.new_title,
                    old_prescription=item.old_prescription,
                    new_prescription=item.new_prescription,
                )
                for item in change.payload.changes
            ],
        ),
        reason=change.reason,
        status=change.status.value,
        created_at=change.created_at,
        resolved_at=change.resolved_at,
        resulting_plan_id=change.resulting_plan_id,
    )


def to_confirm_plan_change_response(result: PlanActivationResult) -> ConfirmPlanChangeResponse:
    resulting = None
    if result.resulting_plan is not None:
        resulting = ResultingPlanResponse(
            id=result.resulting_plan.id,
            version=result.resulting_plan.version,
            status=result.resulting_plan.status.value,
            starts_on=result.resulting_plan.starts_on,
            ends_on=result.resulting_plan.ends_on,
            goal_id=result.resulting_plan.goal_id,
            sessions=[
                PlannedSessionResponse(
                    id=session.id,
                    scheduled_date=session.scheduled_date,
                    session_type=session.session_type.value,
                    title=session.title,
                    prescription=session.prescription,
                )
                for session in result.resulting_sessions
            ],
        )
    return ConfirmPlanChangeResponse(
        plan_change=to_plan_change_response(result.plan_change),
        resulting_plan_id=result.plan_change.resulting_plan_id,
        resulting_plan=resulting,
    )
