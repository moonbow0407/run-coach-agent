"""OpenAI Adapter 的 native tool calling 协议映射（fake SDK response，不调真实模型）。"""

import json

import pytest
from openai import APIError

from app.agent.reasoning.models import (
    AssistantMessage,
    AssistantToolCall,
    ModelRequest,
    ModelToolDefinition,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from app.common.errors import InfrastructureError, ReasonerError
from app.infrastructure.llm.provider import OpenAICompatibleProvider


class FakeCompletions:
    def __init__(self, response) -> None:
        self._response = response
        self.captured_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.captured_kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeClient:
    def __init__(self, response) -> None:
        self.chat = type("Chat", (), {"completions": FakeCompletions(response)})()


class FakeMessage:
    def __init__(self, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeChoice:
    def __init__(self, message) -> None:
        self.message = message


class FakeResponse:
    def __init__(self, message, model: str = "fake-model") -> None:
        self.choices = [FakeChoice(message)]
        self.model = model
        self.usage = None


def _provider(response) -> tuple[OpenAICompatibleProvider, FakeClient]:
    client = FakeClient(response)
    return OpenAICompatibleProvider(client=client, model="fake-model"), client  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_request_translates_five_message_kinds() -> None:
    provider, client = _provider(FakeResponse(FakeMessage(content="好的")))
    request = ModelRequest(
        messages=(
            SystemMessage(content="system text"),
            UserMessage(content="user text"),
            AssistantMessage(content="assistant text"),
            AssistantToolCall(
                tool="get_recent_workouts",
                arguments={"days": 14},
                model_call_id="call_1",
            ),
            ToolResultMessage(model_call_id="call_1", content='{"status":"success"}'),
        ),
        tools=(
            ModelToolDefinition(
                name="get_recent_workouts",
                description="读取训练记录",
                parameters_schema={"type": "object", "properties": {}},
            ),
        ),
    )
    await provider.generate(request)
    kwargs = client.chat.completions.captured_kwargs
    messages = kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "system text"}
    assert messages[1] == {"role": "user", "content": "user text"}
    assert messages[2] == {"role": "assistant", "content": "assistant text"}
    # assistant tool call 必须以 native tool_calls 协议表达，不得伪装进文本。
    assert messages[3]["role"] == "assistant"
    assert messages[3]["tool_calls"][0]["id"] == "call_1"
    assert messages[3]["tool_calls"][0]["function"]["name"] == "get_recent_workouts"
    assert json.loads(messages[3]["tool_calls"][0]["function"]["arguments"]) == {"days": 14}
    # tool result 以 role=tool + tool_call_id 表达。
    assert messages[4]["role"] == "tool"
    assert messages[4]["tool_call_id"] == "call_1"
    assert kwargs["tools"][0]["function"]["name"] == "get_recent_workouts"
    assert kwargs["parallel_tool_calls"] is False
    assert "response_format" not in kwargs


@pytest.mark.asyncio
async def test_response_tool_calls_parsed_to_model_tool_call() -> None:
    raw = FakeToolCall("call_9", "get_workout_feedback", '{"workout_id": "abc"}')
    provider, _ = _provider(FakeResponse(FakeMessage(tool_calls=[raw])))
    response = await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.model_call_id == "call_9"
    assert call.tool == "get_workout_feedback"
    assert call.arguments == {"workout_id": "abc"}


@pytest.mark.asyncio
async def test_unparsable_arguments_is_protocol_failure() -> None:
    raw = FakeToolCall("call_1", "get_recent_workouts", "not-json{")
    provider, _ = _provider(FakeResponse(FakeMessage(tool_calls=[raw])))
    with pytest.raises(ReasonerError, match="无法解析"):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_non_object_arguments_is_protocol_failure() -> None:
    raw = FakeToolCall("call_1", "get_recent_workouts", "[1, 2, 3]")
    provider, _ = _provider(FakeResponse(FakeMessage(tool_calls=[raw])))
    with pytest.raises(ReasonerError, match="不是 JSON 对象"):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_empty_response_fails() -> None:
    provider, _ = _provider(FakeResponse(FakeMessage(content="")))
    with pytest.raises(ReasonerError, match="空输出"):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_api_error_normalized_to_infrastructure_error() -> None:
    provider, _ = _provider(APIError("boom", request=None, body=None))  # type: ignore[arg-type]
    with pytest.raises(InfrastructureError):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_no_tools_no_tools_parameter() -> None:
    provider, client = _provider(FakeResponse(FakeMessage(content="ok")))
    await provider.generate(ModelRequest(messages=(UserMessage(content="hi"),)))
    assert "tools" not in client.chat.completions.captured_kwargs
