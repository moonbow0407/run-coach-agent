"""六个正式 read-only Coaching Tools。

全部复用现有 Coaching Application Service 与 Repository Port，
不直接访问 SQLAlchemy / Session / Repository 实现或 SQL。
参数模型统一 extra="forbid"：缺字段、多字段（含模型注入的 user_id
等可信字段）、类型错误与范围错误都返回 invalid_arguments。
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.workout_service import (
    RECENT_WORKOUTS_LIMIT,
    WorkoutQueryService,
)
from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource


class GetRecentWorkoutsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # strict：拒绝字符串/布尔等隐式强转，与模型可见 JSON Schema
    # 的 integer 声明保持一致，不偷偷改变参数语义。
    days: int = Field(ge=1, le=365, strict=True, description="读取最近多少天的训练记录")


class GetWorkoutDetailArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workout_id: UUID = Field(description="训练记录 ID")


class GetWorkoutFeedbackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workout_id: UUID = Field(description="训练记录 ID")


class GetActiveGoalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetActivePlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetLatestAthleteStateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetRecentWorkoutsTool:
    """读取可信用户最近 1–365 天的训练记录。Phase 2 两个 always-on 之一。"""

    def __init__(self, *, workout_service: WorkoutQueryService) -> None:
        self._workouts = workout_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_recent_workouts",
            description="读取当前用户最近 1–365 天的训练记录列表（日期、距离、时长、心率、类型）。",
            tags=("workout", "training", "recent", "训练", "记录", "最近"),
            search_hint="按天数窗口读取最近训练记录与训练量",
            always_on=True,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[GetRecentWorkoutsArgs]:
        return GetRecentWorkoutsArgs

    async def execute(self, *, args: GetRecentWorkoutsArgs, context: ToolExecutionContext) -> object:
        workouts = await self._workouts.get_recent_workouts(
            user_id=context.user_id, days=args.days
        )
        # 达到硬上限即报告可能截断，让 Agent 知道结果范围（Tool Result Budget）。
        return {
            "days": args.days,
            "count": len(workouts),
            "truncated": len(workouts) >= RECENT_WORKOUTS_LIMIT,
            "workouts": workouts,
        }


class GetWorkoutDetailTool:
    """按 workout_id 读取单次训练（user_id + workout_id 双重过滤，跨用户不可见）。"""

    def __init__(self, *, workout_service: WorkoutQueryService) -> None:
        self._workouts = workout_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_workout_detail",
            description="按 workout_id 读取当前用户单次训练的完整数据。",
            tags=("workout", "detail", "训练", "详情", "单次"),
            search_hint="读取某一次训练的详细数据，例如距离、时长与心率",
            always_on=False,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[GetWorkoutDetailArgs]:
        return GetWorkoutDetailArgs

    async def execute(self, *, args: GetWorkoutDetailArgs, context: ToolExecutionContext) -> object:
        return await self._workouts.get_workout(
            user_id=context.user_id, workout_id=args.workout_id
        )


class GetWorkoutFeedbackTool:
    """读取某次训练的主观反馈。

    返回的是用户报告的主观事实（用力程度 / 主观疲劳 / 酸痛 / 备注），
    不是系统推导的 Athlete State。
    """

    def __init__(self, *, workout_service: WorkoutQueryService) -> None:
        self._workouts = workout_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_workout_feedback",
            description=(
                "按 workout_id 读取当前用户对某次训练的主观反馈："
                "用力程度、主观疲劳、酸痛与备注。这是用户报告的主观事实，"
                "不是系统推导的跑者状态。"
            ),
            tags=("feedback", "subjective", "rpe", "反馈", "主观", "疲劳", "酸痛"),
            search_hint="读取训练后的主观感受、疲劳与酸痛反馈",
            always_on=False,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[GetWorkoutFeedbackArgs]:
        return GetWorkoutFeedbackArgs

    async def execute(
        self, *, args: GetWorkoutFeedbackArgs, context: ToolExecutionContext
    ) -> object:
        return await self._workouts.get_feedback(
            user_id=context.user_id, workout_id=args.workout_id
        )


class GetActiveGoalTool:
    def __init__(self, *, goal_service: GoalQueryService) -> None:
        self._goals = goal_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_active_goal",
            description="读取当前用户当前生效的训练目标（比赛日期、距离、目标成绩）。",
            tags=("goal", "target", "race", "目标", "比赛"),
            search_hint="读取当前训练目标与比赛计划",
            always_on=False,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[GetActiveGoalArgs]:
        return GetActiveGoalArgs

    async def execute(self, *, args: GetActiveGoalArgs, context: ToolExecutionContext) -> object:
        return await self._goals.get_active_goal(user_id=context.user_id)


class GetActivePlanTool:
    def __init__(self, *, plan_service: PlanQueryService) -> None:
        self._plans = plan_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_active_plan",
            description=(
                "读取当前用户当前生效的训练计划摘要与近期课次"
                "（当前周与未来 14 天，最多 20 条）。"
            ),
            tags=("plan", "session", "计划", "课表", "课次"),
            search_hint="读取当前训练计划与接下来安排的课次",
            always_on=False,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[GetActivePlanArgs]:
        return GetActivePlanArgs

    async def execute(self, *, args: GetActivePlanArgs, context: ToolExecutionContext) -> object:
        return await self._plans.get_active_plan_summary(
            user_id=context.user_id, as_of=context.timestamp
        )


class GetLatestAthleteStateTool:
    """只读取已有 latest AthleteStateSnapshot，不现场计算任何状态指标。"""

    def __init__(self, *, athlete_service: AthleteStateQueryService) -> None:
        self._athlete = athlete_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_latest_athlete_state",
            description=(
                "读取当前用户最近一份跑者状态快照（疲劳、恢复、训练负荷、完成率）。"
                "这是已存在的快照，不在现场计算。"
            ),
            tags=("athlete", "state", "fatigue", "recovery", "状态", "疲劳", "恢复"),
            search_hint="读取系统最近一次评估的跑者疲劳与恢复状态",
            always_on=False,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,
            timeout_s=10.0,
        )

    @property
    def args_model(self) -> type[GetLatestAthleteStateArgs]:
        return GetLatestAthleteStateArgs

    async def execute(
        self, *, args: GetLatestAthleteStateArgs, context: ToolExecutionContext
    ) -> object:
        return await self._athlete.get_latest_athlete_state(user_id=context.user_id)
