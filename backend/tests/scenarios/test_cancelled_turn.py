import asyncio

import pytest

from app.agent.lifecycle.events import TurnCancelled, TurnStarted
from app.agent.models.action import FinalAction
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.models import ReasoningContext
from app.common.errors import TurnCancelled as TurnCancelledError
from tests.helpers import event_types, load_turn, load_turn_messages, record_events, request_context_for


class SlowReasoner:
    async def reason(self, context: ReasoningContext) -> FinalAction:
        await asyncio.sleep(30)
        return FinalAction(content="不应该返回")


@pytest.mark.asyncio
async def test_cancelled_turn(
    make_app,
    slice_seed,
    clock,
    sessions,
) -> None:
    app = make_app(reasoner=SlowReasoner())
    events = record_events(app.state.lifecycle)
    context = request_context_for(slice_seed.user_id, clock)
    task = asyncio.create_task(
        app.state.chat_service.send_message(
            request_context=context,
            thread_id=None,
            content="先说到这里",
        )
    )
    for _ in range(100):
        if any(isinstance(event, TurnStarted) for event in events):
            await asyncio.sleep(0.02)
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, TurnCancelledError)):
        await task

    assert "TurnCommitted" not in event_types(events)
    cancelled = next(event for event in events if isinstance(event, TurnCancelled))
    turn = await load_turn(sessions, cancelled.turn_id)
    assert turn.status == TurnStatus.CANCELLED.value
    assert turn.assistant_message_id is None
    messages = await load_turn_messages(sessions, cancelled.turn_id)
    assert [message.role for message in messages] == ["user"]
    assert messages[0].content == "先说到这里"
