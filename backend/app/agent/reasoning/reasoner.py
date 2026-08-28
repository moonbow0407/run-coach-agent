from typing import Protocol

from app.agent.models.action import AgentAction
from app.agent.reasoning.models import ReasoningContext


class Reasoner(Protocol):
    async def reason(self, context: ReasoningContext) -> AgentAction:
        ...
