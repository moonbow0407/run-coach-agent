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
        if any(key in arguments for key in _IDENTITY_KEYS):
            raise CapabilityError("Capability 参数不得包含身份字段")

        handler = {
            "get_recent_workouts": self._get_recent_workouts,
            "get_active_goal": self._get_active_goal,
            "get_active_plan": self._get_active_plan,
            "get_latest_athlete_state": self._get_latest_athlete_state,
        }.get(name)
        if handler is None:
            return Observation(source=name, status="error", error=f"未知能力: {name}")

        argument_error = _validate_arguments(name=name, arguments=arguments)
        if argument_error is not None:
            return Observation(source=name, status="error", error=argument_error)

        try:
            data = await handler(arguments=arguments, context=context)
        except RunCoachError as exc:
            return Observation(source=name, status="error", error=str(exc))
        except Exception as exc:
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
