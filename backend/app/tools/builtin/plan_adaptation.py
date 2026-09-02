"""计划调整提案 Tool：只创建 DRAFT，不激活 Active Plan。"""

from pydantic import BaseModel, ConfigDict, Field

from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource


class ProposePlanAdaptationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_plan_version: int = Field(ge=1, strict=True, description="所依据的当前计划版本")
    based_on_state_version: int = Field(ge=1, strict=True, description="所依据的最新跑者状态版本")
    horizon_days: int = Field(ge=1, le=7, strict=True, description="未来调整窗口天数，1 到 7")
    reason: str = Field(min_length=1, description="提出此次降负荷调整的原因")


class ProposePlanAdaptationTool:
    """提出降负荷调整草案：只创建 DRAFT 变更，激活仍需用户确认流程。"""

    def __init__(self, *, adaptation: PlanAdaptationService) -> None:
        self._adaptation = adaptation

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="propose_plan_adaptation",
            description=(
                "在疲劳为 HIGH 或恢复为 POOR 时，对未来 1–7 天窗口内的节奏/间歇课次"
                "提出降负荷草案（改为恢复休息）。只创建草案，不会激活新计划。"
            ),
            tags=("adaptation", "reduce_load", "降负荷", "调整草案"),
            search_hint="提出降低未来几天节奏或间歇负荷的计划调整草案",
            always_on=False,
            risk=ToolRisk.DRAFT,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[ProposePlanAdaptationArgs]:
        return ProposePlanAdaptationArgs

    async def execute(
        self, *, args: ProposePlanAdaptationArgs, context: ToolExecutionContext
    ) -> object:
        """委托应用服务创建降负荷草案，并回传变更与"比赛未被改动"标记。"""
        change, race_unmodified = await self._adaptation.propose_reduce_upcoming_load(
            user_id=context.user_id,
            turn_id=context.turn_id,
            run_id=context.run_id,
            as_of=context.timestamp,
            based_on_plan_version=args.based_on_plan_version,
            based_on_state_version=args.based_on_state_version,
            horizon_days=args.horizon_days,
            reason=args.reason,
        )
        # 返回草案内容并显式声明 Active Plan 未被改动（DRAFT 风险等级的语义）。
        result: dict[str, object] = {"plan_change": change, "active_plan_unchanged": True}
        if race_unmodified:
            # 比赛课次未被触碰时单独标注，避免模型误以为比赛被调整。
            result["race_session_not_modified"] = True
        return result
