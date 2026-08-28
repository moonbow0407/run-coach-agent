"""ReasoningState：当前 AgentRun 的内存工作状态。

记录本轮已发生的能力调用与观察结果，供下一轮推理参考；
生命周期只覆盖本次 AgentRun，不落库、不承担长期存储。
"""

from dataclasses import dataclass, field

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.models.observation import Observation
from app.common.errors import AgentRuntimeError

ReasoningInteraction = CapabilityCallAction | Observation


@dataclass
class ReasoningState:
    """当前 AgentRun 内存中的工作状态。不保存隐藏思维链，不落库。"""

    interactions: list[ReasoningInteraction] = field(default_factory=list)

    def append(self, item: ReasoningInteraction) -> None:
        if isinstance(item, FinalAction):
            raise AgentRuntimeError("FinalAction 不得进入 ReasoningState")
        self.interactions.append(item)
