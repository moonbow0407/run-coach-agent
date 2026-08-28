"""能力执行结果：回传给模型作为下一轮推理的依据。"""

from typing import Any, Literal

from pydantic import BaseModel


class Observation(BaseModel):
    """一次能力调用的结果。

    成功时 data 为返回数据；失败时 error 为归一化后的错误说明。
    无论成败都会记入 ReasoningState，模型可以据此调整下一步。
    """

    source: str
    status: Literal["success", "error"]
    data: Any | None = None
    error: str | None = None
