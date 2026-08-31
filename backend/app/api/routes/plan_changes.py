"""计划调整确认边界：user_id 只来自 JWT RequestContext。

pending 路由必须在 {plan_change_id} 之前声明，否则 “pending” 会被
当作 UUID 路径参数做校验而返回 422。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies.context import get_request_context
from app.api.errors import to_http_error
from app.api.schemas.plan_changes import (
    ConfirmPlanChangeResponse,
    PlanChangeResponse,
    to_confirm_plan_change_response,
    to_plan_change_response,
)
from app.coaching.application.errors import StalePlanChangeError
from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.common.errors import RunCoachError
from app.common.events import EventMetadata
from app.identity.application.request_context import RequestContext

router = APIRouter()


def _adaptation(request: Request) -> PlanAdaptationService:
    return request.app.state.plan_adaptation_service


@router.get("/api/v1/plan-changes/pending", response_model=PlanChangeResponse)
async def get_pending_plan_change(
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> PlanChangeResponse:
    """读取该用户唯一未解决的提案。

    Agent 的回复文本不携带 plan_change_id，前端训练台靠这个接口
    发现“等用户决定”的提案；没有未解决提案时按 404 报告。
    """
    try:
        change = await _adaptation(request).get_pending(user_id=request_context.user_id)
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    return to_plan_change_response(change)


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
        raise to_http_error(exc) from exc
    return to_plan_change_response(change)


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
            user_id=request_context.user_id,
            plan_change_id=plan_change_id,
            event_metadata=EventMetadata(
                correlation_id=request_context.request_id,
                trace_id=request_context.trace_id,
            ),
        )
    except StalePlanChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale",
                "status": exc.plan_change.status.value,
                "plan_change_id": str(exc.plan_change.id),
                "plan_change": to_plan_change_response(exc.plan_change).model_dump(mode="json"),
            },
        ) from exc
    except RunCoachError as exc:
        raise to_http_error(exc) from exc
    return to_confirm_plan_change_response(result)


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
        raise to_http_error(exc) from exc
    return to_plan_change_response(change)
