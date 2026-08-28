import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.lifecycle.events import TurnCommitted
from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.models.turn import TurnStatus
from app.agent.reasoning.scripted import ScriptedReasoner
from tests.helpers import event_types, load_run_steps, load_turn, record_events


@pytest.mark.asyncio
async def test_recent_training_analysis(
    make_app,
    slice_seed,
    slice_auth_header,
    sessions,
) -> None:
    reasoner = ScriptedReasoner(
        [
            CapabilityCallAction(capability="get_recent_workouts", arguments={"days": 14}),
            FinalAction(content="最近有一次间歇和一次长跑，疲劳为中等。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    events = record_events(app.state.lifecycle)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "我最近训练状态怎么样？"},
            headers=slice_auth_header,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "最近有一次间歇和一次长跑，疲劳为中等。"
    assert "TurnCommitted" in event_types(events)
    assert any(isinstance(event, TurnCommitted) for event in events)

    turn = await load_turn(sessions, body["turn_id"])
    assert turn.status == TurnStatus.COMMITTED.value

    committed = next(event for event in events if isinstance(event, TurnCommitted))
    steps = await load_run_steps(sessions, committed.run_id)
    kinds = [step.kind for step in steps]
    assert "capability_call" in kinds
    assert "observation" in kinds
    assert "final" in kinds
    call = next(step for step in steps if step.kind == "capability_call")
    observation = next(step for step in steps if step.kind == "observation")
    assert call.call_id == observation.call_id
    assert call.input_data is not None
    assert call.input_data["capability"] == "get_recent_workouts"
    assert observation.output_data is not None
    assert observation.output_data["status"] == "success"
    assert len(observation.output_data["data"]) == 4

    bundle = reasoner.seen_contexts[0].context_bundle
    assert bundle.current_input == "我最近训练状态怎么样？"
    assert bundle.working_context.goal is not None
    assert bundle.working_context.goal.target_time_s == 6600
    assert bundle.working_context.latest_athlete_state is not None
    assert bundle.working_context.latest_athlete_state.fatigue_level == "moderate"
