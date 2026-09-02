"""LLM Provider：把具体模型 SDK 与 native tool calling 协议隔离在基础设施层。

Agent / Reasoner 层只依赖 provider-neutral 的 ModelRequest /
ModelResponse；OpenAI 的 tools / tool_calls 协议翻译只发生在本
Adapter，不得把 assistant tool call 或 tool result 序列化进文本
content 伪装传递。
"""

import json
import logging
from typing import Protocol

from openai import APIError, AsyncOpenAI

from app.agent.reasoning.models import (
    AssistantMessage,
    AssistantToolCall,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from app.common.errors import InfrastructureError, ReasonerError

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """LLM Provider 端口：Protocol（结构化鸭子类型，只约束方法签名不要求继承）。"""

    async def generate(self, request: ModelRequest) -> ModelResponse: ...


class OpenAICompatibleProvider:
    """OpenAI 兼容 Adapter，native tool calling 的唯一协议边界。

    client 由调用方注入（生产为 AsyncOpenAI，测试为 fake SDK response），
    本类不构造 SDK 实例。
    """

    def __init__(self, *, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """调用模型并把协议结果转回 provider-neutral 的 ModelResponse。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [_to_openai_message(message) for message in request.messages],
        }
        if request.tools:  # 声明可用工具；并行调用关闭，保证推理循环单步单调用
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
                for tool in request.tools
            ]
            kwargs["parallel_tool_calls"] = False
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APIError as exc:
            raise InfrastructureError("LLM 调用失败") from exc  # SDK 异常归一为基础设施错误

        choice = response.choices[0] if response.choices else None
        message = choice.message if choice else None
        text = (message.content if message is not None else None) or ""
        tool_calls = _parse_tool_calls(message.tool_calls if message is not None else None)
        if not text.strip() and not tool_calls:  # 既无文本也无工具调用：模型空响应
            raise ReasonerError("模型返回空输出")

        usage = None
        if response.usage is not None:
            usage = {
                "prompt_tokens": int(response.usage.prompt_tokens or 0),
                "completion_tokens": int(response.usage.completion_tokens or 0),
            }
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            model=response.model or self._model,
            usage=usage,
        )


def _to_openai_message(message: ModelMessage) -> dict[str, object]:
    """把 provider-neutral 消息翻译为 OpenAI 协议。"""
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": message.content}
    if isinstance(message, UserMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, AssistantMessage):
        return {"role": "assistant", "content": message.content}
    if isinstance(message, AssistantToolCall):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": message.model_call_id,
                    "type": "function",
                    "function": {
                        "name": message.tool,
                        "arguments": json.dumps(
                            message.arguments, ensure_ascii=False
                        ),
                    },
                }
            ],
        }
    if isinstance(message, ToolResultMessage):
        return {
            "role": "tool",
            "tool_call_id": message.model_call_id,
            "content": message.content,
        }
    raise ReasonerError(f"未知模型消息类型: {type(message)!r}")


def _parse_tool_calls(raw_tool_calls: object) -> tuple[ModelToolCall, ...]:
    """把 OpenAI tool_calls 解析为 provider-neutral 形态。

    参数必须是可解析为 JSON 对象的字符串；无法解析或不是对象属于
    typed Reasoner protocol failure，立即失败，不做兜底。
    """
    if not raw_tool_calls:
        return ()
    calls: list[ModelToolCall] = []
    for item in raw_tool_calls:
        call_id = getattr(item, "id", None)
        function = getattr(item, "function", None)
        name = getattr(function, "name", None) if function is not None else None
        raw_arguments = (
            getattr(function, "arguments", None) if function is not None else None
        )
        if not call_id or not name or raw_arguments is None:
            raise ReasonerError("模型返回不完整的 tool call 协议")
        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ReasonerError("模型 tool call 参数无法解析为 JSON") from exc
        if not isinstance(arguments, dict):
            raise ReasonerError("模型 tool call 参数不是 JSON 对象")
        calls.append(
            ModelToolCall(model_call_id=call_id, tool=name, arguments=arguments)
        )
    return tuple(calls)
