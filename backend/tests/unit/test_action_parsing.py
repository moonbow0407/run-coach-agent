import pytest

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.reasoning.action_parser import parse_agent_action
from app.common.errors import ReasonerError


def test_parse_capability_call() -> None:
    action = parse_agent_action(
        '{"type":"capability_call","capability":"get_recent_workouts","arguments":{"days":14}}'
    )
    assert isinstance(action, CapabilityCallAction)
    assert action.capability == "get_recent_workouts"
    assert action.arguments == {"days": 14}


def test_parse_final_action() -> None:
    action = parse_agent_action('{"type":"final","content":"最近状态还可以"}')
    assert isinstance(action, FinalAction)
    assert action.content == "最近状态还可以"


def test_parse_fenced_json() -> None:
    action = parse_agent_action("```json\n{\"type\":\"final\",\"content\":\"ok\"}\n```")
    assert isinstance(action, FinalAction)


def test_invalid_json_fails() -> None:
    with pytest.raises(ReasonerError):
        parse_agent_action("not-json")


def test_unknown_action_type_fails() -> None:
    with pytest.raises(ReasonerError):
        parse_agent_action('{"type":"tool_call","name":"x"}')
