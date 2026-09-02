"""LLMReasoner 的 native 响应归一化：单 Action 语义与协议失败边界。"""

import pytest

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.llm_reasoner import LLMReasoner
from app.agent.reasoning.models import (
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from app.common.errors import ReasonerError


class FakeProvider:
    """模型 Provider 替身：记录收到的请求并回放预置响应。"""

    def __init__(self, response: ModelResponse) -> None:
        self._response = response
        self.requests: list[ModelRequest] = []

    async def generate(
        self, request: ModelRequest, on_text_delta: object | None = None
    ) -> ModelResponse:
        self.requests.append(request)
        return self._response


def _response(text: str = "", tool_calls: tuple[ModelToolCall, ...] = ()) -> ModelResponse:
    """构造一段文本 + 若干 tool call 的模型响应。"""
    return ModelResponse(text=text, model="fake", tool_calls=tool_calls)


def _tool_call(call_id: str = "call_1", tool: str = "get_recent_workouts") -> ModelToolCall:
    """构造一条工具调用（默认读取最近训练）。"""
    return ModelToolCall(model_call_id=call_id, tool=tool, arguments={"days": 14})


@pytest.mark.asyncio
async def test_single_tool_call_maps_to_tool_call_action() -> None:
    """验证：单 tool call 归一化为 ToolCallAction，并保留调用 id 供配对。"""
    provider = FakeProvider(_response(tool_calls=(_tool_call(),)))
    reasoner = LLMReasoner(provider, _renderer_stub())
    action = await reasoner.reason(_context_stub())
    assert isinstance(action, ToolCallAction)
    assert action.tool == "get_recent_workouts"
    assert action.arguments == {"days": 14}
    assert action.model_call_id == "call_1"


@pytest.mark.asyncio
async def test_tool_call_with_side_text_discards_text() -> None:
    """验证：伴随 tool call 的闲聊文本被丢弃（单 Action 语义）。"""
    provider = FakeProvider(_response(text="我顺便说一句", tool_calls=(_tool_call(),)))
    reasoner = LLMReasoner(provider, _renderer_stub())
    action = await reasoner.reason(_context_stub())
    assert isinstance(action, ToolCallAction)


@pytest.mark.asyncio
async def test_text_only_response_maps_to_final_action() -> None:
    """验证：纯文本响应归一化为 FinalAction，内容原样保留。"""
    provider = FakeProvider(_response(text="最近训练状态不错。"))
    reasoner = LLMReasoner(provider, _renderer_stub())
    action = await reasoner.reason(_context_stub())
    assert isinstance(action, FinalAction)
    assert action.content == "最近训练状态不错。"


@pytest.mark.asyncio
async def test_multiple_tool_calls_fail() -> None:
    """验证：一次返回多个 tool call 视为协议失败，不猜测执行顺序。"""
    provider = FakeProvider(
        _response(tool_calls=(_tool_call("call_1"), _tool_call("call_2")))
    )
    reasoner = LLMReasoner(provider, _renderer_stub())
    # pytest.raises：断言抛出 ReasonerError，match 校验错误信息含指定文案
    with pytest.raises(ReasonerError, match="多个 Tool Call"):
        await reasoner.reason(_context_stub())


@pytest.mark.asyncio
async def test_empty_response_fails() -> None:
    """验证：空白输出视为协议失败，而非当作空回复继续。"""
    provider = FakeProvider(_response(text="  "))
    reasoner = LLMReasoner(provider, _renderer_stub())
    with pytest.raises(ReasonerError, match="空输出"):
        await reasoner.reason(_context_stub())


@pytest.mark.asyncio
async def test_renderer_receives_visible_tools() -> None:
    # Reasoner 把 visible_tools 原样传给 renderer（动态 Schema 链路）。
    provider = FakeProvider(_response(text="ok"))
    renderer = _renderer_stub()
    reasoner = LLMReasoner(provider, renderer)
    await reasoner.reason(_context_stub())
    assert renderer.received_tools == [("visible_stub",)]


def _renderer_stub():
    """Prompt 渲染器替身：记录每次收到的可见工具并返回空请求。"""
    class RendererStub:
        def __init__(self) -> None:
            self.received_tools: list[tuple] = []

        def render(self, bundle, state, visible_tools):
            self.received_tools.append(tuple(visible_tools))
            return ModelRequest(messages=())

    return RendererStub()


def _context_stub():
    """推理上下文替身：只携带固定的可见工具名。"""
    class ContextStub:
        context_bundle = None
        state = None
        visible_tools = ("visible_stub",)

    return ContextStub()
