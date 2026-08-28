"""ReasoningState 不变量：ToolCallAction -> 同 model_call_id 的 Observation 严格交替。"""

import pytest

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.observation import Observation
from app.agent.reasoning.state import ReasoningState
from app.common.errors import AgentRuntimeError


def _action(model_call_id: str = "call_a") -> ToolCallAction:
    return ToolCallAction(tool="get_recent_workouts", arguments={"days": 7}, model_call_id=model_call_id)


def _observation(model_call_id: str = "call_a") -> Observation:
    return Observation(
        source="get_recent_workouts", status="success", data=[], model_call_id=model_call_id
    )


def test_valid_sequence_is_accepted() -> None:
    state = ReasoningState()
    action = _action("call_a")
    state.append(action)
    state.append(_observation("call_a"))
    state.append(_action("call_b"))
    state.append(_observation("call_b"))
    assert [type(item).__name__ for item in state.interactions] == [
        "ToolCallAction",
        "Observation",
        "ToolCallAction",
        "Observation",
    ]


def test_orphan_observation_fails() -> None:
    state = ReasoningState()
    with pytest.raises(AgentRuntimeError, match="紧邻"):
        state.append(_observation())


def test_missing_observation_before_next_call_fails() -> None:
    state = ReasoningState()
    state.append(_action("call_a"))
    with pytest.raises(AgentRuntimeError, match="尚无对应的 Observation"):
        state.append(_action("call_b"))


def test_model_call_id_mismatch_fails() -> None:
    state = ReasoningState()
    state.append(_action("call_a"))
    with pytest.raises(AgentRuntimeError, match="不一致"):
        state.append(_observation("call_b"))


def test_duplicate_model_call_id_fails() -> None:
    state = ReasoningState()
    state.append(_action("call_a"))
    state.append(_observation("call_a"))
    with pytest.raises(AgentRuntimeError, match="重复"):
        state.append(_action("call_a"))


def test_final_action_rejected() -> None:
    state = ReasoningState()
    with pytest.raises(AgentRuntimeError, match="FinalAction"):
        state.append(FinalAction(content="done"))  # type: ignore[arg-type]


def test_constructor_validates_sequence() -> None:
    # 快照构造（如 ScriptedReasoner）也必须满足不变量。
    with pytest.raises(AgentRuntimeError):
        ReasoningState(interactions=[_observation()])
