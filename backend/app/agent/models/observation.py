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

    source: str  # 产生该结果的工具名 / 来源标识
    status: Literal["success", "error"]  # 工具执行是否成功
    data: Any | None = None  # 成功时的返回数据，结构由具体工具决定
    error_code: str | None = None  # 失败时的结构化错误码（ToolErrorCode）
    error: str | None = None  # 失败时的安全错误说明，不含敏感细节
    model_call_id: str = Field(min_length=1)  # 触发本次结果的模型协议 ID，回传时用于配对
