"""模型每轮推理必须产出的两种 Action 之一。

这是 Reasoner 与 Runtime 之间的输出契约：要么通过 native tool calling
请求调用某个工具，要么声明证据已足够并给出最终回答。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallAction(BaseModel):
    """请求调用一个工具（tool 为工具名，arguments 为模型给出的业务参数）。

    model_call_id 是模型供应商返回的 opaque 协议 ID，仅用于把 Observation
    回传为下一轮请求的 tool result；内部 Trace（ToolExecutionContext /
    Lifecycle / RunStep）使用 Runtime 生成的 UUID call_id，两者不混用。
    """

    type: Literal["tool_call"] = "tool_call"
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    model_call_id: str = Field(min_length=1)


class FinalAction(BaseModel):
    """结束推理：content 即给用户的最终回答。"""

    type: Literal["final"] = "final"
    content: str


# 模型单轮输出的合法类型合集
AgentAction = ToolCallAction | FinalAction
