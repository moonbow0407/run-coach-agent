"""计划调整确认边界：user_id 只来自 JWT RequestContext。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies.context import get_request_context
from app.api.schemas.plan_changes import (
    ConfirmPlanChangeResponse,
    PlanChangePayloadResponse,
    PlanChangeResponse,
    PlannedSessionResponse,
    ResultingPlanResponse,
    SessionChangeResponse,
)
from app.coaching.application.errors import StalePlanChangeError
from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.coaching.domain.plan.models import PlanChange
from app.coaching.ports.plan_activation_store import PlanActivationResult
from app.common.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RunCoachError,
)
from app.identity.application.request_context import RequestContext

router = APIRouter()


def _adaptation(request: Request) -> PlanAdaptationService:
    return request.app.state.plan_adaptation_service


@router.get("/api/v1/plan-changes/{plan_change_id}", response_model=PlanChangeResponse)
async def get_plan_change(
    plan_change_id: UUID,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> PlanChangeResponse:
    try:
        change = await _adaptation(request).get(
            user_id=request_context.user_id, plan_change_id=plan_change_id
        )
    except RunCoachError as exc:
        raise _http_error(exc) from exc
    return _plan_change_response(change)


@router.post(
    "/api/v1/plan-changes/{plan_change_id}/confirm",
    response_model=ConfirmPlanChangeResponse,
)
async def confirm_plan_change(
    plan_change_id: UUID,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> ConfirmPlanChangeResponse:
    try:
        result = await _adaptation(request).confirm(
            user_id=request_context.user_id, plan_change_id=plan_change_id
        )
    except StalePlanChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale",
                "status": exc.plan_change.status.value,
                "plan_change_id": str(exc.plan_change.id),
                "plan_change": _plan_change_response(exc.plan_change).model_dump(mode="json"),
            },
        ) from exc
    except RunCoachError as exc:
        raise _http_error(exc) from exc
    return _confirm_response(result)


@router.post(
    "/api/v1/plan-changes/{plan_change_id}/reject",
    response_model=PlanChangeResponse,
)
async def reject_plan_change(
    plan_change_id: UUID,
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> PlanChangeResponse:
    try:
        change = await _adaptation(request).reject(
            user_id=request_context.user_id, plan_change_id=plan_change_id
        )
    except RunCoachError as exc:
        raise _http_error(exc) from exc
    return _plan_change_response(change)


def _plan_change_response(change: PlanChange) -> PlanChangeResponse:
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


def _confirm_response(result: PlanActivationResult) -> ConfirmPlanChangeResponse:
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
        plan_change=_plan_change_response(result.plan_change),
        resulting_plan_id=result.plan_change.resulting_plan_id,
        resulting_plan=resulting,
    )


def _http_error(exc: RunCoachError) -> HTTPException:
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, DomainError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
