"""LLMReasoner：Reasoner 的真实实现。

流程：渲染 Prompt → 调用 LLM Provider → 把模型输出解析成结构化 Action。
模型 SDK 被 Provider 隔离，本类不感知具体供应商。
"""

from app.agent.models.action import AgentAction
from app.agent.reasoning.action_parser import parse_agent_action
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.common.errors import ReasonerError
from app.infrastructure.llm.provider import LLMProvider


class LLMReasoner:
    """把上下文交给模型，并把模型输出解析为下一步 Action。"""

    def __init__(self, provider: LLMProvider, renderer: PromptRenderer) -> None:
        self._provider = provider
        self._renderer = renderer

    async def reason(self, context: ReasoningContext) -> AgentAction:
        request = self._renderer.render(context.context_bundle, context.state)
        response = await self._provider.generate(request)
        # 空输出视为失败而不是重试 / 兜底，交由上层按失败语义收尾。
        if not response.text.strip():
            raise ReasonerError("模型返回空输出")
        return parse_agent_action(response.text)
