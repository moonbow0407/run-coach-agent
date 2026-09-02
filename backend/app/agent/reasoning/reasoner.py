"""Reasoner 接口：AgentRuntime 依赖的推理抽象。

具体实现可以是 LLMReasoner（真实模型）、ScriptedReasoner（测试脚本）
或未来其它混合实现；Runtime 与模型 SDK 通过本接口彻底解耦。
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.agent.models.action import AgentAction
from app.agent.reasoning.models import ReasoningContext

# 文本增量监听器：流式产出最终回答文本时被逐片段调用；None 表示调用方不关心增量
TextDeltaListener = Callable[[str], Awaitable[None]]


# Protocol（结构化鸭子类型）：只约束方法签名，实现方无需显式继承本类
class Reasoner(Protocol):
    """给定上下文与已发生的交互，决定下一步 Action（调用能力或给出最终回答）。

    on_text_delta 是可选的副作用通道：实现方在流式产出回答文本时逐片段调用，
    不改变返回值语义——reason 仍只返回一个完整 Action，增量不构成消息。
    """

    async def reason(
        self,
        context: ReasoningContext,
        on_text_delta: TextDeltaListener | None = None,
    ) -> AgentAction:
        ...
