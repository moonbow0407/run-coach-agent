"""训练分析 Tools：调用 Coaching Application，不实现负荷算法。"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.coaching.application.training_analysis_service import TrainingAnalysisService
from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource


class AnalyzeTrainingLoadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyzeWorkoutArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workout_id: UUID = Field(description="要分析的训练记录 ID")


class AnalyzeTrainingLoadTool:
    def __init__(self, *, analysis: TrainingAnalysisService) -> None:
        self._analysis = analysis

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="analyze_training_load",
            description=(
                "按可信 as_of 计算最近 7 日与前 7 日的时长、距离、质量课次数、"
                "session-RPE 合计与覆盖率。缺失 RPE 不补值；结果可能是 partial。"
            ),
            tags=("srpe", "load", "coverage", "sRPE"),
            search_hint="analyze_training_load session-RPE coverage duration distance",
            always_on=False,
            risk=ToolRisk.ANALYZE,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[AnalyzeTrainingLoadArgs]:
        return AnalyzeTrainingLoadArgs

    async def execute(
        self, *, args: AnalyzeTrainingLoadArgs, context: ToolExecutionContext
    ) -> object:
        return await self._analysis.analyze_training_load(
            user_id=context.user_id, as_of=context.timestamp
        )


class AnalyzeWorkoutTool:
    def __init__(self, *, analysis: TrainingAnalysisService) -> None:
        self._analysis = analysis

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="analyze_workout",
            description=(
                "对某次课做确定性分析：距离时长心率、已记录的用力程度、session-RPE、"
                "是否质量课、同日课表上下文。不会把同日课表当成已完成。"
            ),
            tags=("session_rpe", "quality_session", "analyze_workout"),
            search_hint="analyze_workout session-RPE heart-rate same-day planned sessions",
            always_on=False,
            risk=ToolRisk.ANALYZE,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[AnalyzeWorkoutArgs]:
        return AnalyzeWorkoutArgs

    async def execute(self, *, args: AnalyzeWorkoutArgs, context: ToolExecutionContext) -> object:
        analysis = await self._analysis.analyze_workout(
            user_id=context.user_id,
            workout_id=args.workout_id,
            as_of=context.timestamp,
        )
        return {
            "workout": analysis.workout,
            "feedback": analysis.feedback,
            "session_rpe_load": analysis.session_rpe_load,
            "quality_session": analysis.quality_session,
            "same_day_planned_sessions": analysis.same_day_planned_sessions,
            "heart_rate": {
                "avg": analysis.workout.avg_heart_rate,
                "max": analysis.workout.max_heart_rate,
            },
        }
