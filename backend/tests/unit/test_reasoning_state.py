import pytest

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.models.observation import Observation
from app.agent.reasoning.state import ReasoningState
from app.common.errors import AgentRuntimeError


def test_interactions_keep_call_then_observation_order() -> None:
    state = ReasoningState()
    action = CapabilityCallAction(capability="get_recent_workouts", arguments={"days": 7})
    observation = Observation(source="get_recent_workouts", status="success", data=[])
    state.append(action)
    state.append(observation)
    assert state.interactions == [action, observation]


def test_final_action_must_not_enter_state() -> None:
    state = ReasoningState()
    with pytest.raises(AgentRuntimeError):
        state.append(FinalAction(content="done"))  # type: ignore[arg-type]
