"""LLM Provider：把具体模型 SDK 隔离在基础设施层。

Agent / Reasoning 层只依赖 LLMProvider 接口；更换模型供应商
（OpenAI / 兼容 API / 未来其它）不影响 Agent Core。
"""

from typing import Protocol

from openai import APIError, AsyncOpenAI

from app.agent.reasoning.models import ModelMessage, ModelRequest, ModelResponse
from app.common.errors import InfrastructureError, ReasonerError


class LLMProvider(Protocol):
    """统一的模型调用接口。"""

    async def generate(self, request: ModelRequest) -> ModelResponse:
        ...


class OpenAICompatibleProvider:
    """基于 OpenAI 兼容 Chat Completions API 的实现。"""

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """调用模型并归一化结果；SDK 异常统一转 InfrastructureError。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [_to_openai(message) for message in request.messages],
        }
        if request.json_object:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APIError as exc:
            # 边界处归一化：不让 SDK 异常类型泄漏进 Agent / Domain 层。
            raise InfrastructureError("LLM 调用失败") from exc

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content if choice and choice.message else None) or ""
        if not text.strip():
            raise ReasonerError("模型返回空输出")
        usage = None
        # usage 只保留 prompt / completion 两项 token 计数，供观测与成本核算。
        if response.usage is not None:
            usage = {
                "prompt_tokens": int(response.usage.prompt_tokens or 0),
                "completion_tokens": int(response.usage.completion_tokens or 0),
            }
        return ModelResponse(text=text, model=response.model or self._model, usage=usage)


def _to_openai(message: ModelMessage) -> dict[str, str]:
    return {"role": message.role, "content": message.content}
