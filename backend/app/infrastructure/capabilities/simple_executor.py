"""SimpleCapabilityExecutor：Phase 1 的能力执行器（临时 adapter）。

负责把模型给出的能力名与参数路由到对应领域查询服务，并执行安全约束：
参数中不得出现身份字段，参数严格校验，错误归一化为 Observation。
Phase 2 会被完整 Tool Runtime（注册 / 目录 / 搜索 / 执行）替换。
"""

from collections.abc import Mapping
from typing import Any

from app.agent.models.observation import Observation
from app.agent.ports.capability_executor import CapabilityExecutionContext
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.workout_service import WorkoutQueryService
from app.common.errors import CapabilityError, RunCoachError
from app.infrastructure.jsonutil import json_ready

_IDENTITY_KEYS = {"user_id", "userId"}


class SimpleCapabilityExecutor:
    """Phase 1 临时 adapter。Phase 2 删除并替换为 Tool Runtime。"""

    def __init__(
        self,
        workout_service: WorkoutQueryService,
        goal_service: GoalQueryService,
        plan_service: PlanQueryService,
        athlete_service: AthleteStateQueryService,
    ) -> None:
        self._workouts = workout_service
        self._goals = goal_service
        self._plans = plan_service
        self._athlete = athlete_service

    async def execute(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> Observation:
        """执行一次能力调用，返回 Observation（错误也归一化进 Observation）。"""
        # 身份隔离：模型参数不得夹带身份字段，user_id 只来自可信 context。
        if any(key in arguments for key in _IDENTITY_KEYS):
            raise CapabilityError("Capability 参数不得包含身份字段")

        handler = {
            "get_recent_workouts": self._get_recent_workouts,
            "get_active_goal": self._get_active_goal,
            "get_active_plan": self._get_active_plan,
            "get_latest_athlete_state": self._get_latest_athlete_state,
        }.get(name)
        if handler is None:
            # 未知能力：作为可观察的错误返回给模型，让它自行调整。
            return Observation(source=name, status="error", error=f"未知能力: {name}")

        # 参数不合法：同样以 Observation 回传，不中断整个 Run。
        argument_error = _validate_arguments(name=name, arguments=arguments)
        if argument_error is not None:
            return Observation(source=name, status="error", error=argument_error)

        try:
            data = await handler(arguments=arguments, context=context)
        except RunCoachError as exc:
            # 已知业务失败归一化为错误 Observation。
            return Observation(source=name, status="error", error=str(exc))
        except Exception as exc:
            # 未知异常属于协议/系统故障，不是模型可自行修复的错误：上抛处理。
            raise CapabilityError("能力执行失败") from exc

        return Observation(source=name, status="success", data=json_ready(data))

    async def _get_recent_workouts(
        self,
        *,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> object:
        days = arguments["days"]
        if not isinstance(days, int) or isinstance(days, bool):
            raise CapabilityError("get_recent_workouts.days 必须是整数")
        workouts = await self._workouts.get_recent_workouts(user_id=context.user_id, days=days)
        return workouts

    async def _get_active_goal(
        self,
        *,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> object:
        return await self._goals.get_active_goal(user_id=context.user_id)

    async def _get_active_plan(
        self,
        *,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> object:
        return await self._plans.get_active_plan(user_id=context.user_id)

    async def _get_latest_athlete_state(
        self,
        *,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> object:
        return await self._athlete.get_latest_athlete_state(user_id=context.user_id)


def _validate_arguments(*, name: str, arguments: Mapping[str, Any]) -> str | None:
    """白名单式参数校验：只允许能力声明的参数，返回错误文案或 None。"""
    if name == "get_recent_workouts":
        unexpected = set(arguments) - {"days"}
        if unexpected:
            return f"get_recent_workouts 包含未知参数: {sorted(unexpected)}"
        days = arguments.get("days")
        if not isinstance(days, int) or isinstance(days, bool):
            return "get_recent_workouts.days 必须是整数"
        if not 1 <= days <= 365:
            return "get_recent_workouts.days 必须在 1–365 之间"
        return None

    if arguments:
        return f"{name} 不接受参数"
    return None
