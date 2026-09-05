"""安全状态只读边界：训练台芯片与 get_safety_status Tool 共用 SafetyGate。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.context import get_request_context
from app.api.schemas.safety import SafetyStatusResponse
from app.identity.application.request_context import RequestContext
from app.tools.safety.gate import SafetyGate

router = APIRouter()


def _safety_gate(request: Request) -> SafetyGate:
    return request.app.state.safety_gate


@router.get("/api/v1/safety/status", response_model=SafetyStatusResponse)
async def get_safety_status(
    request_context: Annotated[RequestContext, Depends(get_request_context)],
    request: Request,
) -> SafetyStatusResponse:
    """读取当前用户安全约束：ok / flags / reasons。"""
    status = await _safety_gate(request).status_for(user_id=request_context.user_id)
    return SafetyStatusResponse(
        ok=status.ok,
        flags=list(status.flags),
        reasons=list(status.reasons),
    )
