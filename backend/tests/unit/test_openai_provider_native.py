"""OpenAI Adapter 的 native tool calling 协议映射（fake SDK response，不调真实模型）。"""

import asyncio
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
    """SDK completions 替身：捕获请求参数，回放预置响应或抛出异常。"""

    def __init__(self, response) -> None:
        self._response = response
        self.captured_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.captured_kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeClient:
    """SDK client 替身：只提供 chat.completions 入口。"""

    def __init__(self, response) -> None:
        self.chat = type("Chat", (), {"completions": FakeCompletions(response)})()


class FakeMessage:
    """assistant 消息替身：文本与 tool_calls 二选一。"""

    def __init__(self, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeFunction:
    """tool function 替身：名称 + JSON 字符串形式的参数。"""

    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    """tool call 替身：字段名与 OpenAI 原生协议保持一致。"""

    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeChoice:
    """choice 替身：包一层 message，模拟响应结构。"""

    def __init__(self, message) -> None:
        self.message = message


class FakeResponse:
    """completion 响应替身：单 choice，usage 缺省。"""

    def __init__(self, message, model: str = "fake-model") -> None:
        self.choices = [FakeChoice(message)]
        self.model = model
        self.usage = None


def _provider(response) -> tuple[OpenAICompatibleProvider, FakeClient]:
    """组装被测 Provider 与替身 client；返回 client 以便断言捕获的请求参数。"""
    client = FakeClient(response)
    return OpenAICompatibleProvider(client=client, model="fake-model"), client  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_request_translates_five_message_kinds() -> None:
    """验证：五种内部消息类型逐一映射为 OpenAI 消息协议，工具定义随请求传参。"""
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
    """验证：原生 tool call 响应解析回内部 ModelToolCall（参数 JSON 反序列化）。"""
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
    """验证：参数不是合法 JSON 视为协议失败，不猜测意图。"""
    raw = FakeToolCall("call_1", "get_recent_workouts", "not-json{")
    provider, _ = _provider(FakeResponse(FakeMessage(tool_calls=[raw])))
    with pytest.raises(ReasonerError, match="无法解析"):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_non_object_arguments_is_protocol_failure() -> None:
    """验证：参数是合法 JSON 但不是对象（如数组），同样拒绝。"""
    raw = FakeToolCall("call_1", "get_recent_workouts", "[1, 2, 3]")
    provider, _ = _provider(FakeResponse(FakeMessage(tool_calls=[raw])))
    with pytest.raises(ReasonerError, match="不是 JSON 对象"):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_empty_response_fails() -> None:
    """验证：空文本响应视为失败，不产出空 Action。"""
    provider, _ = _provider(FakeResponse(FakeMessage(content="")))
    with pytest.raises(ReasonerError, match="空输出"):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_api_error_normalized_to_infrastructure_error() -> None:
    """验证：SDK 异常归一化为 InfrastructureError，不向外泄漏 SDK 类型。"""
    provider, _ = _provider(APIError("boom", request=None, body=None))  # type: ignore[arg-type]
    with pytest.raises(InfrastructureError):
        await provider.generate(ModelRequest(messages=(SystemMessage(content="s"),)))


@pytest.mark.asyncio
async def test_no_tools_no_tools_parameter() -> None:
    """验证：无工具时不发送 tools 参数（部分兼容网关拒绝空数组）。"""
    provider, client = _provider(FakeResponse(FakeMessage(content="ok")))
    await provider.generate(ModelRequest(messages=(UserMessage(content="hi"),)))
    assert "tools" not in client.chat.completions.captured_kwargs


# ---------- 流式路径（on_text_delta 模式） ----------


class FakeStreamDeltaFunction:
    """流式 tool call 的 function 分片：name 只在首片出现，arguments 逐片增量。"""

    def __init__(self, name: str | None = None, arguments: str = "") -> None:
        self.name = name
        self.arguments = arguments


class FakeStreamDeltaToolCall:
    """流式 tool call 分片替身：index 是聚合键，字段名对齐 OpenAI 协议。"""

    def __init__(
        self,
        index: int,
        call_id: str | None = None,
        name: str | None = None,
        arguments: str = "",
    ) -> None:
        self.index = index
        self.id = call_id
        self.type = "function" if call_id else None
        self.function = FakeStreamDeltaFunction(name=name, arguments=arguments)


class FakeStreamDelta:
    """流式 delta 替身：content / tool_calls / reasoning_content 按需携带。"""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[FakeStreamDeltaToolCall] | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class FakeStreamChoice:
    """流式 choice 替身：包一层 delta。"""

    def __init__(self, delta: FakeStreamDelta) -> None:
        self.delta = delta


class FakeStreamChunk:
    """流式 chunk 替身：字段名对齐 OpenAI ChatCompletionChunk；choices 可为空。"""

    def __init__(self, choices: list[FakeStreamChoice], model: str = "fake-model") -> None:
        self.choices = choices
        self.model = model


class FakeAsyncStream:
    """异步流替身：支持 async with / async for，回放 chunk 序列，可在末尾抛错。"""

    def __init__(self, chunks: list[FakeStreamChunk], error: Exception | None = None) -> None:
        self._chunks = list(chunks)
        self._error = error
        self.closed = False  # 断言「取消/异常后流已关闭、连接不泄漏」

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.closed = True
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._error is not None:
            raise self._error
        raise StopAsyncIteration


class FakeStreamingCompletions:
    """流式 SDK 替身：记录请求参数，校验回调模式必须走 stream=True。"""

    def __init__(self, stream: FakeAsyncStream) -> None:
        self._stream = stream
        self.captured_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.captured_kwargs = kwargs
        assert kwargs.get("stream") is True, "传入 on_text_delta 时必须走流式请求"
        return self._stream


def _stream_provider(
    stream: FakeAsyncStream,
) -> tuple[OpenAICompatibleProvider, FakeStreamingCompletions]:
    """组装流式被测 Provider；返回 completions 替身以便断言捕获的请求参数。"""
    completions = FakeStreamingCompletions(stream)
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    provider = OpenAICompatibleProvider(client=client, model="fake-model")
    return provider, completions  # type: ignore[arg-type]


def _stream_request() -> ModelRequest:
    """构造最小流式请求：单条系统消息。"""
    return ModelRequest(messages=(SystemMessage(content="s"),))


async def _noop_delta(_fragment: str) -> None:
    """不关心增量的回调替身：与生产签名的 await 协议保持一致。"""


@pytest.mark.asyncio
async def test_stream_forwards_text_deltas_in_order() -> None:
    """验证：文本按 chunk 顺序逐片段回调，聚合文本与回调序列一致。"""
    stream = FakeAsyncStream(
        [
            FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="你"))]),
            FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="好"))]),
        ]
    )
    provider, completions = _stream_provider(stream)
    deltas: list[str] = []

    async def on_text_delta(fragment: str) -> None:
        deltas.append(fragment)

    response = await provider.generate(_stream_request(), on_text_delta)
    assert deltas == ["你", "好"]
    assert response.text == "你好"
    assert response.tool_calls == ()
    assert response.model == "fake-model"
    # 流式模式必须带 stream=True，且 v1 不绑定 include_usage
    assert completions.captured_kwargs["stream"] is True
    assert "stream_options" not in completions.captured_kwargs


@pytest.mark.asyncio
async def test_stream_tool_calls_aggregated_by_index() -> None:
    """验证：tool call 分片按 index 聚合（id/name 首片、arguments 拼接），全程不回调文本。"""
    stream = FakeAsyncStream(
        [
            FakeStreamChunk(
                [
                    FakeStreamChoice(
                        FakeStreamDelta(
                            tool_calls=[
                                FakeStreamDeltaToolCall(
                                    0,
                                    call_id="call_1",
                                    name="get_recent_workouts",
                                    arguments='{"workout',
                                )
                            ]
                        )
                    )
                ]
            ),
            FakeStreamChunk(
                [
                    FakeStreamChoice(
                        FakeStreamDelta(
                            tool_calls=[FakeStreamDeltaToolCall(0, arguments='_id": "a"}')]
                        )
                    )
                ]
            ),
        ]
    )
    provider, _ = _stream_provider(stream)
    deltas: list[str] = []

    async def on_text_delta(fragment: str) -> None:
        deltas.append(fragment)

    response = await provider.generate(_stream_request(), on_text_delta)
    assert deltas == []  # tool call 轮次不外推任何文本
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.model_call_id == "call_1"
    assert call.tool == "get_recent_workouts"
    assert call.arguments == {"workout_id": "a"}


@pytest.mark.asyncio
async def test_stream_content_after_tool_calls_never_forwarded() -> None:
    """验证不变量：一旦出现 tool_calls 分片，本流内此后文本一律不再回调。"""
    stream = FakeAsyncStream(
        [
            FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="先说的话"))]),
            FakeStreamChunk(
                [
                    FakeStreamChoice(
                        FakeStreamDelta(
                            tool_calls=[FakeStreamDeltaToolCall(0, call_id="c1", name="t", arguments="{}")]
                        )
                    )
                ]
            ),
            FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="不该外推的话"))]),
        ]
    )
    provider, _ = _stream_provider(stream)
    deltas: list[str] = []

    async def on_text_delta(fragment: str) -> None:
        deltas.append(fragment)

    response = await provider.generate(_stream_request(), on_text_delta)
    # 协议异常顺序（先文本后 tool_calls）下：早前片段已外推不可撤回，
    # 但 tool_calls 出现后的文本必须被挡住；聚合响应保持完整由 Reasoner 判定。
    assert deltas == ["先说的话"]
    assert response.text == "先说的话不该外推的话"
    assert len(response.tool_calls) == 1


@pytest.mark.asyncio
async def test_stream_reasoning_content_ignored() -> None:
    """验证：思考过程增量（reasoning_content）本期不展示，只转发正文片段。"""
    stream = FakeAsyncStream(
        [
            FakeStreamChunk(
                [
                    FakeStreamChoice(
                        FakeStreamDelta(reasoning_content="内部思考", content=None)
                    )
                ]
            ),
            FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="答案"))]),
        ]
    )
    provider, _ = _stream_provider(stream)
    deltas: list[str] = []

    async def on_text_delta(fragment: str) -> None:
        deltas.append(fragment)

    response = await provider.generate(_stream_request(), on_text_delta)
    assert deltas == ["答案"]
    assert response.text == "答案"


@pytest.mark.asyncio
async def test_stream_usage_only_chunk_skipped() -> None:
    """验证：choices 为空的收尾统计包不参与解析，流正常结束不报错。"""
    stream = FakeAsyncStream(
        [
            FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="ok"))]),
            FakeStreamChunk([]),  # usage-only 收尾包
        ]
    )
    provider, _ = _stream_provider(stream)
    deltas: list[str] = []

    async def on_text_delta(fragment: str) -> None:
        deltas.append(fragment)

    response = await provider.generate(_stream_request(), on_text_delta)
    assert deltas == ["ok"]
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_stream_midway_api_error_normalized() -> None:
    """验证：迭代中途的 SDK 异常归一化为 InfrastructureError，且流被关闭。"""
    stream = FakeAsyncStream(
        [FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content="半截"))])],
        error=APIError("boom", request=None, body=None),
    )
    provider, _ = _stream_provider(stream)
    with pytest.raises(InfrastructureError):
        await provider.generate(_stream_request(), on_text_delta=_noop_delta)
    assert stream.closed


@pytest.mark.asyncio
async def test_stream_empty_output_fails() -> None:
    """验证：流式下无文本也无 tool call 同样视为空输出失败。"""
    stream = FakeAsyncStream([FakeStreamChunk([FakeStreamChoice(FakeStreamDelta(content=None))])])
    provider, _ = _stream_provider(stream)
    with pytest.raises(ReasonerError, match="空输出"):
        await provider.generate(_stream_request(), on_text_delta=_noop_delta)


@pytest.mark.asyncio
async def test_stream_cancellation_propagates_and_closes() -> None:
    """验证：取消信号在流迭代中直接穿透（不包装），并关闭流防连接泄漏。"""

    class HangStream(FakeAsyncStream):
        """挂起的流：模拟模型迟迟不产出，用于触发取消。"""

        async def __anext__(self):
            await asyncio.sleep(10)
            raise StopAsyncIteration

    stream = HangStream([])
    provider, _ = _stream_provider(stream)
    task = asyncio.create_task(
        provider.generate(_stream_request(), on_text_delta=_noop_delta)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
