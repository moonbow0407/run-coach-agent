"""训练计划查询服务。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from app.coaching.domain.plan.models import PlannedSession, TrainingPlan
from app.coaching.ports.plan_repository import PlanRepository

# Tool Result Budget：get_active_plan 与 WorkingContext 共用的课次时间窗与硬上限。
PLAN_SESSION_WINDOW_DAYS = 14
PLAN_SESSION_MAX_COUNT = 20


@dataclass(frozen=True)
class ActivePlanSummary:
    """受 Tool Result Budget 约束的当前计划摘要。

    课次范围 = as_of 所在 ISO 周 ∪ as_of 起 14 天（两段连续，合并为
    [window_start, window_end]）；按日期排序后总课次数不超过
    PLAN_SESSION_MAX_COUNT，超出部分显式截断（truncated=True）。
    WorkingContext 与 get_active_plan 共用同一摘要语义，
    ContextBundle 不携带完整长期计划。
    """

    plan: TrainingPlan
    sessions: tuple[PlannedSession, ...]
    window_start: date
    window_end: date
    truncated: bool


class PlanQueryService:
    def __init__(self, repository: PlanRepository) -> None:
        self._repository = repository

    async def get_active_plan_summary(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
    ) -> ActivePlanSummary | None:
        """读取当前生效计划的受控摘要（无生效计划返回 None）。

        as_of 是请求的可信时间基准（来自 ToolExecutionContext / 请求上下文），
        不使用服务器墙钟，保证同一请求内窗口口径一致。
        """
        plan = await self._repository.get_active(user_id=user_id)
        if plan is None:
            return None
        sessions = await self._repository.list_sessions(user_id=user_id, plan_id=plan.id)

        window_start = as_of.date() - timedelta(days=as_of.weekday())
        window_end = as_of.date() + timedelta(days=PLAN_SESSION_WINDOW_DAYS - 1)
        scoped = sorted(
            (
                session
                for session in sessions
                if window_start <= session.scheduled_date <= window_end
            ),
            key=lambda session: (session.scheduled_date, session.title),
        )
        truncated = len(scoped) > PLAN_SESSION_MAX_COUNT
        return ActivePlanSummary(
            plan=plan,
            sessions=tuple(scoped[:PLAN_SESSION_MAX_COUNT]),
            window_start=window_start,
            window_end=window_end,
            truncated=truncated,
        )
