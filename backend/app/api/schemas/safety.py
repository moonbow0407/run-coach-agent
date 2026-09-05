"""安全状态 API 的响应模型。"""

from pydantic import BaseModel, ConfigDict, Field


class SafetyStatusResponse(BaseModel):
    """当前用户的教练安全约束快照（与 get_safety_status Tool 同口径）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool  # True 表示无限制性 flag
    flags: list[str] = Field(default_factory=list)  # 触发的约束 flag 码
    reasons: list[str] = Field(default_factory=list)  # 面向用户的中文说明
