import asyncio

import pytest
from pydantic import BaseModel, ConfigDict

from app.agent.lifecycle.events import ToolCompleted, TurnCancelled, TurnStarted
from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.scripted import ScriptedReasoner
from app.common.errors import TurnCancelled as TurnCancelledError
from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource
from tests.helpers import (
    event_types,
    load_turn,
    load_turn_messages,
    record_events,
    request_context_for,
)


class SlowReasoner:
    async def reason(self, context: ReasoningContext) -> FinalAction:
        await asyncio.sleep(30)
        return FinalAction(content="不应该返回")


class CancellableProbeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CancellableProbeTool:
    """等待取消的探测 Tool，用事件明确证明取消已传播到执行体。"""

    def __init__(self, *, started: asyncio.Event, cancelled: asyncio.Event) -> None:
        self._started = started
        self._cancelled = cancelled

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="cancellable_probe",
            description="仅用于验证 Tool 执行期间的取消传播。",
            tags=("probe",),
            search_hint="probe",
            always_on=True,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.SYSTEM,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[CancellableProbeArgs]:
        return CancellableProbeArgs

    async def execute(
        self,
        *,
        args: CancellableProbeArgs,
        context: ToolExecutionContext,
    ) -> object:
        self._started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self._cancelled.set()
            raise
        return {}


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


@pytest.mark.asyncio
async def test_cancelled_turn_stops_running_tool(
    make_app,
    slice_seed,
    clock,
    sessions,
) -> None:
    """用户取消 Turn 时，正在执行的 Tool 立即停止且不产生完成事件。"""
    tool_started = asyncio.Event()
    tool_cancelled = asyncio.Event()
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="cancellable_probe",
                arguments={},
                model_call_id="call-cancel-1",
            )
        ]
    )
    app = make_app(reasoner=reasoner)
    app.state.tool_registry.register(
        CancellableProbeTool(started=tool_started, cancelled=tool_cancelled)
    )
    events = record_events(app.state.lifecycle)
    context = request_context_for(slice_seed.user_id, clock)
    task = asyncio.create_task(
        app.state.chat_service.send_message(
            request_context=context,
            thread_id=None,
            content="执行工具后取消",
        )
    )

    await asyncio.wait_for(tool_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(tool_cancelled.wait(), timeout=1)

    assert not any(isinstance(event, ToolCompleted) for event in events)
    assert "TurnCommitted" not in event_types(events)
    cancelled = next(event for event in events if isinstance(event, TurnCancelled))
    turn = await load_turn(sessions, cancelled.turn_id)
    assert turn.status == TurnStatus.CANCELLED.value
    assert turn.assistant_message_id is None
