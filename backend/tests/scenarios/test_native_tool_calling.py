"""Phase 2 必过场景：Native Tool Calling Contract（FakeProvider 走完整 Runtime）。

FakeProvider 模拟 OpenAI SDK 行为（接收 native 请求、返回 tool call 或文本），
穿过 LLMReasoner -> AgentRuntime -> ToolRuntime 全链路，验证动态 Schema
下发、model_call_id 往返与消息状态还原。
"""

import json

import pytest

from app.agent.reasoning.llm_reasoner import LLMReasoner
from app.agent.reasoning.models import ModelRequest, ModelResponse, ModelToolCall
from app.agent.reasoning.prompt_renderer import PromptRenderer
from tests.helpers import load_run_steps, request_context_for


class FakeNativeProvider:
    """记录每次请求并按脚本返回 native 响应的 Provider 替身。"""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("FakeNativeProvider 脚本已用尽")
        return self._responses.pop(0)


def _tool_call_response(call_id: str, tool: str, arguments: dict) -> ModelResponse:
    return ModelResponse(
        text="",
        model="fake-native",
        tool_calls=(ModelToolCall(model_call_id=call_id, tool=tool, arguments=arguments),),
    )


def _final_response(content: str) -> ModelResponse:
    return ModelResponse(text=content, model="fake-native")


@pytest.mark.asyncio
async def test_native_tool_calling_contract_end_to_end(
    make_app,
    slice_seed,
    clock,
    sessions,
) -> None:
    """场景 11：动态 Schema 传给 Provider；model_call_id 往返；文本转 FinalAction。"""
    workout_id = slice_seed.workout_ids[-1]
    provider = FakeNativeProvider(
        [
            _tool_call_response("native-1", "get_recent_workouts", {"days": 7}),
            _tool_call_response(
                "native-2", "search_tools", {"query": "主观反馈", "limit": 3}
            ),
            _tool_call_response(
                "native-3", "get_workout_feedback", {"workout_id": str(workout_id)}
            ),
            _final_response("上次间歇课反馈为用力 8、疲劳 7。"),
        ]
    )
    reasoner = LLMReasoner(provider, PromptRenderer())
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    result = await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="我上次训练感觉怎么样？",
    )

    assert result.content == "上次间歇课反馈为用力 8、疲劳 7。"

    # 1) 动态可见 Tool Schema 逐轮传给 Provider（native tools 参数）。
    first_tools = {tool.name for tool in provider.requests[0].tools}
    assert first_tools == {"search_tools", "get_recent_workouts"}
    third_tools = {tool.name for tool in provider.requests[2].tools}
    assert "get_workout_feedback" in third_tools

    # 2) 第二次请求还原了第一次的 assistant tool call + tool result（native 形态）。
    from app.agent.reasoning.models import AssistantToolCall, ToolResultMessage

    second_messages = provider.requests[1].messages
    tool_call_messages = [
        message for message in second_messages if isinstance(message, AssistantToolCall)
    ]
    result_messages = [
        message for message in second_messages if isinstance(message, ToolResultMessage)
    ]
    assert len(tool_call_messages) == 1
    assert tool_call_messages[0].model_call_id == "native-1"
    assert tool_call_messages[0].tool == "get_recent_workouts"
    assert len(result_messages) == 1
    assert result_messages[0].model_call_id == "native-1"
    payload = json.loads(result_messages[0].content)
    assert payload["status"] == "success"
    assert payload["model_call_id"] == "native-1"

    # 3) Trace：内部 call_id 与 model_call_id 不混淆，成对关联。
    steps = await load_run_steps(sessions, result.run_id)
    tool_calls = [step for step in steps if step.kind == "tool_call"]
    observations = [step for step in steps if step.kind == "observation"]
    assert len(tool_calls) == 3
    model_ids = [step.input_data["model_call_id"] for step in tool_calls]
    assert model_ids == ["native-1", "native-2", "native-3"]
    for call, obs in zip(tool_calls, observations, strict=True):
        assert call.call_id == obs.call_id
        assert obs.output_data["model_call_id"] == call.input_data["model_call_id"]
        # 内部 call_id 是 UUID，与模型协议 ID 不同源。
        assert str(call.call_id) != call.input_data["model_call_id"]


@pytest.mark.asyncio
async def test_native_provider_visible_tools_contains_search_after_unlock(
    make_app,
    slice_seed,
    clock,
) -> None:
    """发现后的下一轮请求中，解锁 Tool 的 Schema 连同参数模型一起下发。"""
    provider = FakeNativeProvider(
        [
            _tool_call_response("native-1", "search_tools", {"query": "训练计划"}),
            _final_response("找到了。"),
        ]
    )
    reasoner = LLMReasoner(provider, PromptRenderer())
    app = make_app(reasoner=reasoner)
    context = request_context_for(slice_seed.user_id, clock)
    await app.state.chat_service.send_message(
        request_context=context,
        thread_id=None,
        content="帮我看看计划工具",
    )
    second_tools = provider.requests[1].tools
    plan_tool = next(tool for tool in second_tools if tool.name == "get_active_plan")
    # Schema 由 Pydantic 参数模型生成（含 title 等生成特征）。
    assert plan_tool.parameters_schema["type"] == "object"
    assert "properties" in plan_tool.parameters_schema
