"""测试用 Reasoner 替身：不依赖真实模型即可验证 Runtime 循环。

ScriptedReasoner 按预定序列返回 Action；FailingReasoner 直接抛错，
用于验证失败语义。
"""

from collections.abc import Sequence

from app.agent.models.action import AgentAction, FinalAction
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.reasoner import TextDeltaListener
from app.agent.reasoning.state import ReasoningState
from app.common.errors import ReasonerError


class ScriptedReasoner:
    """按预定 Action 序列返回，用于稳定验证 Runtime，不依赖真实模型。"""

    def __init__(self, actions: Sequence[AgentAction]) -> None:
        self._actions = list(actions)
        self._index = 0  # 下一次 reason 应返回的 Action 下标
        self.seen_contexts: list[ReasoningContext] = []  # 测试断言用：记录每次收到的上下文

    async def reason(
        self,
        context: ReasoningContext,
        on_text_delta: TextDeltaListener | None = None,
    ) -> AgentAction:
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
            # 预定序列用尽说明 Runtime 循环次数与测试预期不符，直接失败
            raise ReasonerError("ScriptedReasoner 已用尽预定 Action")
        action = self._actions[self._index]
        self._index += 1
        if isinstance(action, FinalAction) and on_text_delta is not None:
            # 与真实流式行为对齐：最终回答经增量通道整段推送一次；tool call 不推
            await on_text_delta(action.content)
        return action


class FailingReasoner:
    """恒定抛错的 Reasoner 替身，用于验证失败传播语义。"""

    def __init__(self, error: Exception | None = None) -> None:
        # 可注入自定义异常；默认抛 ReasonerError
        self._error = error or ReasonerError("预定失败")

    async def reason(
        self,
        context: ReasoningContext,
        on_text_delta: TextDeltaListener | None = None,
    ) -> AgentAction:
        raise self._error
