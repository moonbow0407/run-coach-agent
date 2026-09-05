"""安全状态只读 Tool：让模型可发现并解释当前约束。"""

from pydantic import BaseModel, ConfigDict

from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource
from app.tools.safety.gate import SafetyGate


class GetSafetyStatusArgs(BaseModel):
    """无参数：只读取可信上下文中的用户身份。"""

    model_config = ConfigDict(extra="forbid")


class GetSafetyStatusTool:
    """返回当前用户安全约束快照；always-on，便于模型在提案前自检。"""

    def __init__(self, *, safety_gate: SafetyGate) -> None:
        self._gate = safety_gate

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_safety_status",
            description=(
                "读取当前用户的教练安全约束："
                "是否放行（ok）、触发的 flags 与中文 reasons。"
                "在提出计划调整前可先调用，以便向用户解释限制。"
            ),
            tags=("safety", "governance", "安全", "约束", "伤痛"),
            search_hint="查看当前是否因疲劳或伤痛限制计划调整",
            always_on=True,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=5.0,
        )

    @property
    def args_model(self) -> type[GetSafetyStatusArgs]:
        return GetSafetyStatusArgs

    async def execute(self, *, args: GetSafetyStatusArgs, context: ToolExecutionContext) -> object:
        status = await self._gate.status_for(user_id=context.user_id)
        return {
            "ok": status.ok,
            "flags": list(status.flags),
            "reasons": list(status.reasons),
        }
