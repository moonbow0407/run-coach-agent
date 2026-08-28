"""模型每轮推理必须产出的两种 Action 之一。

这是 Reasoner 与 Runtime 之间的输出契约：要么请求调用某个能力，
要么声明证据已足够并给出最终回答。由 action_parser 从模型输出解析而来。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class CapabilityCallAction(BaseModel):
    """请求调用一个领域能力（capability 为能力名，arguments 为模型给出的参数）。"""

    type: Literal["capability_call"] = "capability_call"
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class FinalAction(BaseModel):
    """结束推理：content 即给用户的最终回答。"""

    type: Literal["final"] = "final"
    content: str


# 模型单轮输出的合法类型合集
AgentAction = CapabilityCallAction | FinalAction
