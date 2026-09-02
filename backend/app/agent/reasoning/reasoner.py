"""Reasoner 接口：AgentRuntime 依赖的推理抽象。

具体实现可以是 LLMReasoner（真实模型）、ScriptedReasoner（测试脚本）
或未来其它混合实现；Runtime 与模型 SDK 通过本接口彻底解耦。
"""

from typing import Protocol

from app.agent.models.action import AgentAction
from app.agent.reasoning.models import ReasoningContext


# Protocol（结构化鸭子类型）：只约束方法签名，实现方无需显式继承本类
class Reasoner(Protocol):
    """给定上下文与已发生的交互，决定下一步 Action（调用能力或给出最终回答）。"""

    async def reason(self, context: ReasoningContext) -> AgentAction:
        ...
