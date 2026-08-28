from app.agent.models.action import AgentAction
from app.agent.reasoning.action_parser import parse_agent_action
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.common.errors import ReasonerError
from app.infrastructure.llm.provider import LLMProvider


class LLMReasoner:
    def __init__(self, provider: LLMProvider, renderer: PromptRenderer) -> None:
        self._provider = provider
        self._renderer = renderer

    async def reason(self, context: ReasoningContext) -> AgentAction:
        request = self._renderer.render(context.context_bundle, context.state)
        response = await self._provider.generate(request)
        if not response.text.strip():
            raise ReasonerError("模型返回空输出")
        return parse_agent_action(response.text)
