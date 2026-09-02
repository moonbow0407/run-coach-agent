"""LLMReasoner：Reasoner 的真实实现（native tool calling）。

流程：渲染 native 消息与动态 Tool 定义 → 调用 LLM Provider → 把
native 响应归一化为单 Action（Phase 2 单 Action 语义）。
模型 SDK 与供应商 tool calling 协议被 Provider 隔离，本类不感知供应商。
"""

from app.agent.models.action import AgentAction, FinalAction, ToolCallAction
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.agent.reasoning.reasoner import TextDeltaListener
from app.common.errors import ReasonerError
from app.infrastructure.llm.provider import LLMProvider


class LLMReasoner:
    """把上下文与可见 Tool 交给模型，并把 native 响应归一化为下一步 Action。"""

    def __init__(self, provider: LLMProvider, renderer: PromptRenderer) -> None:
        self._provider = provider
        self._renderer = renderer

    async def reason(
        self,
        context: ReasoningContext,
        on_text_delta: TextDeltaListener | None = None,
    ) -> AgentAction:
        """渲染上下文为 native 请求，调用模型并归一化为单个 Action。

        on_text_delta 原样透传给 Provider：是否流式、增量如何外推都是
        Provider 的协议细节，本类只面向聚合完成的 ModelResponse 做判定。
        """
        # 把上下文 + 已发生交互 + 当前可见 Tool 渲染成完整模型请求
        request = self._renderer.render(
            context.context_bundle, context.state, context.visible_tools
        )
        # 供应商协议细节由 Provider 隔离，这里只面向归一化后的响应
        response = await self._provider.generate(request, on_text_delta)

        if len(response.tool_calls) > 1:
            # 单 Action 语义：不选第一个、不并行执行，明确失败。
            raise ReasonerError(
                f"模型返回多个 Tool Call（{len(response.tool_calls)} 个），"
                "Phase 2 每轮只允许一个 Action"
            )
        if response.tool_calls:
            call = response.tool_calls[0]
            # 附带文本不构成 Canonical Assistant Message，直接丢弃。
            return ToolCallAction(
                tool=call.tool,
                arguments=call.arguments,
                model_call_id=call.model_call_id,
            )
        if not response.text.strip():
            # 空输出视为失败而不是重试 / 兜底，交由上层按失败语义收尾。
            raise ReasonerError("模型返回空输出")
        return FinalAction(content=response.text)
