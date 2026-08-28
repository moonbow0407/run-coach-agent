"""工具执行结果：回传给模型作为下一轮推理的依据。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """一次工具调用的结果。

    成功时 data 为返回数据；失败时 error_code 为结构化错误码
    （ToolErrorCode），error 为归一化后的安全错误说明，不包含数据库地址、
    密钥或内部堆栈。model_call_id 与触发本次结果的 ToolCallAction 一致
    （成功与错误都保留），使下一轮模型请求能构造合法 tool result。
    无论成败都会记入 ReasoningState，模型可以据此调整下一步。
    """

    source: str
    status: Literal["success", "error"]
    data: Any | None = None
    error_code: str | None = None
    error: str | None = None
    model_call_id: str = Field(min_length=1)
