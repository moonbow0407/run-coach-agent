"""LLM Provider：把具体模型 SDK 与 native tool calling 协议隔离在基础设施层。

Agent / Reasoner 层只依赖 provider-neutral 的 ModelRequest /
ModelResponse；OpenAI 的 tools / tool_calls 协议翻译只发生在本
Adapter，不得把 assistant tool call 或 tool result 序列化进文本
content 伪装传递。
"""

import json
import logging
from dataclasses import dataclass
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
from app.agent.reasoning.reasoner import TextDeltaListener
from app.common.errors import InfrastructureError, ReasonerError

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """LLM Provider 端口：Protocol（结构化鸭子类型，只约束方法签名不要求继承）。

    on_text_delta 非空时走流式调用并逐片段回调文本增量；None 为一次性调用。
    """

    async def generate(
        self,
        request: ModelRequest,
        on_text_delta: TextDeltaListener | None = None,
    ) -> ModelResponse: ...


class OpenAICompatibleProvider:
    """OpenAI 兼容 Adapter，native tool calling 的唯一协议边界。

    client 由调用方注入（生产为 AsyncOpenAI，测试为 fake SDK response），
    本类不构造 SDK 实例。
    """

    def __init__(self, *, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self,
        request: ModelRequest,
        on_text_delta: TextDeltaListener | None = None,
    ) -> ModelResponse:
        """调用模型并把协议结果转回 provider-neutral 的 ModelResponse。

        两种路径返回完全一致的 ModelResponse；区别只在文本增量是否边生成边外推。
        """
        kwargs = self._build_kwargs(request)
        if on_text_delta is None:
            return await self._generate_once(kwargs)
        return await self._generate_stream(kwargs, on_text_delta)

    def _build_kwargs(self, request: ModelRequest) -> dict[str, object]:
        """构造 OpenAI chat.completions 请求参数（工具声明与消息翻译）。"""
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
        return kwargs

    async def _generate_once(self, kwargs: dict[str, object]) -> ModelResponse:
        """一次性调用：等完整响应后统一解析。"""
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APIError as exc:
            logger.exception("llm.provider.call_failed", extra={"model": self._model})
            raise InfrastructureError("LLM 调用失败") from exc  # SDK 异常归一为基础设施错误

        choice = response.choices[0] if response.choices else None
        message = choice.message if choice else None
        text = (message.content if message is not None else None) or ""
        tool_calls = _parse_tool_calls(message.tool_calls if message is not None else None)
        if not text.strip() and not tool_calls:  # 既无文本也无工具调用：模型空响应
            raise ReasonerError("模型返回空输出")
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            model=response.model or self._model,
            usage=_normalize_usage(response.usage),
        )

    async def _generate_stream(
        self, kwargs: dict[str, object], on_text_delta: TextDeltaListener
    ) -> ModelResponse:
        """流式调用：逐 chunk 转发文本增量，同时聚合出完整 ModelResponse。

        不变量：一旦出现 tool_calls 分片，本流内永不调用 on_text_delta——
        tool call 轮次的附带文本会被 Reasoner 丢弃、不落库，绝不能先推给用户。
        本期不传 stream_options，usage 保持 None（当前无消费者）。
        """
        text_parts: list[str] = []
        # tool_calls 按 index 聚合：id / name 只在首片出现，arguments 逐片拼接
        tool_fragments: dict[int, _StreamToolCallFragments] = {}
        seen_tool_calls = False
        model_name = self._model
        try:
            stream = await self._client.chat.completions.create(**kwargs, stream=True)
            # async with：正常结束或中途取消（CancelledError）都会关闭流，防连接泄漏
            async with stream:
                async for chunk in stream:
                    model_name = chunk.model or model_name
                    # 收尾统计包 choices 为空，必须先跳过再取 choices[0]
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(delta, "tool_calls", None):
                        # tool call 轮次：聚合分片，且本流内不再外推任何文本
                        seen_tool_calls = True
                        for item in delta.tool_calls:
                            slot = tool_fragments.setdefault(
                                item.index, _StreamToolCallFragments()
                            )
                            if item.id:
                                slot.id = item.id
                            if getattr(item, "function", None) is not None:
                                if item.function.name:
                                    slot.name = item.function.name
                                if item.function.arguments:
                                    slot.arguments += item.function.arguments
                        continue
                    fragment = getattr(delta, "content", None)
                    # 思考过程增量（reasoning_content）本期不展示，直接忽略。
                    # tool_calls 之后的文本仍忠实聚合进响应（由 Reasoner 统一
                    # 丢弃），但绝不再外推给用户。
                    if fragment:
                        text_parts.append(fragment)
                        if not seen_tool_calls:
                            await on_text_delta(fragment)
        except APIError as exc:
            logger.exception("llm.provider.stream_failed", extra={"model": self._model})
            raise InfrastructureError("LLM 调用失败") from exc

        text = "".join(text_parts)
        tool_calls = _parse_tool_calls(
            [fragments.to_raw() for fragments in tool_fragments.values()]
        )
        if not text.strip() and not tool_calls:  # 既无文本也无工具调用：模型空响应
            raise ReasonerError("模型返回空输出")
        return ModelResponse(
            text=text, tool_calls=tool_calls, model=model_name, usage=None
        )


@dataclass
class _StreamToolCallFragments:
    """同一路 tool call 的流式分片聚合槽（index 相同的分片落到同一槽）。"""

    id: str = ""  # 模型协议 ID，首片携带
    name: str = ""  # 工具名，首片携带
    arguments: str = ""  # JSON 参数字符串，逐片拼接

    def to_raw(self) -> "_StreamRawToolCall":
        """转成 _parse_tool_calls 可读取的形状（getattr 协议兼容）。"""
        return _StreamRawToolCall(id=self.id, function=_StreamRawFunction(name=self.name, arguments=self.arguments))


@dataclass(frozen=True)
class _StreamRawToolCall:
    """聚合后的流式 tool call；字段形状对齐 SDK 非流式响应的 tool_call 对象。"""

    id: str
    function: "_StreamRawFunction"


@dataclass(frozen=True)
class _StreamRawFunction:
    """聚合后的 function 字段（name + 完整 arguments JSON 字符串）。"""

    name: str
    arguments: str


def _normalize_usage(usage: object) -> dict[str, int] | None:
    """把 SDK usage 对象归一化为 token 统计字典；无 usage 时返回 None。"""
    if usage is None:
        return None
    return {
        "prompt_tokens": int(usage.prompt_tokens or 0),
        "completion_tokens": int(usage.completion_tokens or 0),
    }


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
