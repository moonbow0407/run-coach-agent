"""Phase 5 固定 durable event → task routing。"""

from datetime import datetime

from app.agent.contracts.durable_events import (
    TURN_CANCELLED_V1,
    TURN_COMMITTED_V1,
    TURN_FAILED_V1,
    validate_agent_event,
)
from app.coaching.contracts.durable_events import (
    ATHLETE_STATE_RECOMPUTED_V1,
    PLAN_CHANGE_CONFIRMED_V1,
    WORKOUT_CHANGED_V1,
    WORKOUT_FEEDBACK_CHANGED_V1,
    validate_coaching_event,
)
from app.common.errors import DomainError
from app.common.events import DurableEventEnvelope
from app.workers.contracts import TASK_VERSION, WorkerTaskEnvelope

# 四类 v1 任务名：路由表、handler 注册表与恢复扫描共用同一口径。
FINALIZE_TERMINAL_TURN = "finalize_terminal_turn"
RECOMPUTE_ATHLETE_STATE = "recompute_athlete_state"
PROJECT_SEMANTIC_MEMORY = "project_semantic_memory"
PROJECT_EPISODE = "project_episode"

# 事件类型 → 任务名列表的固定路由表：一个事件可派生多个任务。
_ROUTES: dict[str, tuple[str, ...]] = {
    TURN_COMMITTED_V1: (FINALIZE_TERMINAL_TURN, PROJECT_SEMANTIC_MEMORY),
    TURN_FAILED_V1: (FINALIZE_TERMINAL_TURN,),
    TURN_CANCELLED_V1: (FINALIZE_TERMINAL_TURN,),
    WORKOUT_CHANGED_V1: (RECOMPUTE_ATHLETE_STATE,),
    WORKOUT_FEEDBACK_CHANGED_V1: (RECOMPUTE_ATHLETE_STATE,),
    ATHLETE_STATE_RECOMPUTED_V1: (PROJECT_EPISODE,),
    PLAN_CHANGE_CONFIRMED_V1: (PROJECT_EPISODE,),
}


def route_event(
    event: DurableEventEnvelope, *, enqueued_at: datetime
) -> tuple[WorkerTaskEnvelope, ...]:
    """按固定路由表把一个持久化事件转成一个或多个任务信封。"""
    names = _ROUTES.get(event.event_type)
    if names is None:
        # 路由表未收录的事件类型：不支持，报领域错误。
        raise DomainError("unsupported_durable_event_schema")
    # 按事件所属域校验 payload 契约，防止坏数据进入队列。
    if event.event_type.startswith("conversation."):
        validate_agent_event(event)
    else:
        validate_coaching_event(event)
    return tuple(
        WorkerTaskEnvelope(
            task_name=name,
            task_version=TASK_VERSION,
            event=event,
            enqueued_at=enqueued_at,
        )
        for name in names
    )


def event_types_for_task(task_name: str) -> tuple[str, ...]:
    """恢复扫描使用的固定 route 反向索引。"""
    event_types = tuple(
        event_type for event_type, task_names in _ROUTES.items() if task_name in task_names
    )
    if not event_types:
        raise DomainError("unknown_worker_task_route")
    return event_types


def validate_task_route(task: WorkerTaskEnvelope) -> None:
    """消费前校验任务信封与当前路由表一致：版本或任务名对不上即拒绝。"""
    expected = route_event(task.event, enqueued_at=task.enqueued_at)
    if task.task_version != TASK_VERSION or task.task_name not in {
        item.task_name for item in expected
    }:
        raise DomainError("invalid_worker_task_route")
