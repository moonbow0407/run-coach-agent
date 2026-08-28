"""测试用 Reasoner 替身：不依赖真实模型即可验证 Runtime 循环。

ScriptedReasoner 按预定序列返回 Action；FailingReasoner 直接抛错，
用于验证失败语义。
"""

from collections.abc import Sequence

from app.agent.models.action import AgentAction
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.state import ReasoningState
from app.common.errors import ReasonerError


class ScriptedReasoner:
    """按预定 Action 序列返回，用于稳定验证 Runtime，不依赖真实模型。"""

    def __init__(self, actions: Sequence[AgentAction]) -> None:
        self._actions = list(actions)
        self._index = 0
        self.seen_contexts: list[ReasoningContext] = []

    async def reason(self, context: ReasoningContext) -> AgentAction:
        # 快照 interactions 与可见 Tool：Runtime 会原地追加，
        # 测试需要看到当轮调用时的状态。
        self.seen_contexts.append(
            ReasoningContext(
                context_bundle=context.context_bundle,
                state=ReasoningState(interactions=list(context.state.interactions)),
                visible_tools=list(context.visible_tools),
            )
        )
        if self._index >= len(self._actions):
            raise ReasonerError("ScriptedReasoner 已用尽预定 Action")
        action = self._actions[self._index]
        self._index += 1
        return action


class FailingReasoner:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or ReasonerError("预定失败")

    async def reason(self, context: ReasoningContext) -> AgentAction:
        raise self._error
