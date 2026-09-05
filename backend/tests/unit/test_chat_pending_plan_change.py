"""ChatResult / ChatResponse 挂载未解决计划调整 CTA。"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.agent.application.chat_service import (
    ChatResult,
    ChatService,
    PendingPlanChangeData,
    SessionDiffSummaryData,
    _actions_for,
    _pending_from_change,
)
from app.api.routes.chat import _completed_sse_payload, _to_chat_response
from app.coaching.domain.plan.models import (
    PlanChange,
    PlanChangePayload,
    PlanChangeStatus,
    PlanChangeType,
    SessionChange,
    SessionType,
)
from app.common.ids import new_id


def _change(*, status: PlanChangeStatus) -> PlanChange:
    return PlanChange(
        id=new_id(),
        user_id=uuid4(),
        from_plan_id=new_id(),
        from_plan_version=2,
        based_on_state_id=new_id(),
        based_on_state_version=1,
        source_turn_id=new_id(),
        source_run_id=new_id(),
        as_of=datetime(2026, 9, 8, tzinfo=UTC),
        change_type=PlanChangeType.REDUCE_UPCOMING_LOAD,
        payload=PlanChangePayload(
            horizon_days=7,
            changes=(
                SessionChange(
                    source_session_id=new_id(),
                    scheduled_date=date(2026, 9, 10),
                    from_type=SessionType.INTERVAL,
                    to_type=SessionType.REST,
                    old_title="间歇",
                    new_title="休息",
                    old_prescription={"distance_m": 8000},
                    new_prescription={},
                ),
            ),
        ),
        reason="近期疲劳偏高，先降强度",
        status=status,
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
        resolved_at=None,
        resulting_plan_id=None,
    )


def test_pending_summary_and_actions_for_confirmation() -> None:
    """验证：待确认提案生成摘要，并开放 confirm/reject 动作。"""
    change = _change(status=PlanChangeStatus.PENDING_CONFIRMATION)
    pending = _pending_from_change(change)
    assert isinstance(pending, PendingPlanChangeData)
    assert pending.from_plan_version == 2
    assert len(pending.session_diffs) == 1
    assert pending.session_diffs[0].from_type == "interval"
    assert _actions_for(change) == ("confirm_plan_change", "reject_plan_change")


def test_draft_has_summary_but_no_actions() -> None:
    """验证：草案仍可出现在 CTA 摘要中，但不开放确认动作。"""
    change = _change(status=PlanChangeStatus.DRAFT)
    assert _actions_for(change) == ()
    pending = _pending_from_change(change)
    assert pending.status == "draft"


def test_chat_response_and_sse_payload_include_pending() -> None:
    """验证：同步响应与 SSE run.completed 都带 pending_plan_change。"""
    pending = PendingPlanChangeData(
        id=new_id(),
        change_type="reduce_upcoming_load",
        reason="降负荷",
        status="pending_confirmation",
        from_plan_version=3,
        session_diffs=(
            SessionDiffSummaryData(
                scheduled_date=date(2026, 9, 11),
                from_type="tempo",
                to_type="easy",
                old_title="节奏",
                new_title="轻松",
            ),
        ),
    )
    result = ChatResult(
        thread_id=new_id(),
        turn_id=new_id(),
        message_id=new_id(),
        content="建议先降强度。",
        run_id=new_id(),
        pending_plan_change=pending,
        actions=("confirm_plan_change", "reject_plan_change"),
    )
    response = _to_chat_response(result)
    assert response.pending_plan_change is not None
    assert response.pending_plan_change.id == pending.id
    assert response.actions == ["confirm_plan_change", "reject_plan_change"]
    payload = _completed_sse_payload(result)
    assert payload["pending_plan_change"]["change_type"] == "reduce_upcoming_load"
    assert payload["actions"] == ["confirm_plan_change", "reject_plan_change"]


@pytest.mark.asyncio
async def test_chat_service_loads_pending_when_adaptation_injected() -> None:
    """验证：ChatService 在注入 PlanAdaptation 后能挂载未解决提案。"""

    class _FakeAdaptation:
        def __init__(self, change: PlanChange) -> None:
            self._change = change

        async def get_unresolved(self, *, user_id):
            return self._change

    change = _change(status=PlanChangeStatus.PENDING_CONFIRMATION)
    service = ChatService(
        conversation_store=None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        lifecycle=None,  # type: ignore[arg-type]
        plan_adaptation_service=_FakeAdaptation(change),
    )
    pending, actions = await service._load_pending_cta(user_id=change.user_id)
    assert pending is not None
    assert pending.id == change.id
    assert actions == ("confirm_plan_change", "reject_plan_change")
