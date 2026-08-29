"""ORM Row -> 领域对象 的映射层。

数据库行结构（Row）不越过本层进入领域；
字符串字段在这里转成领域枚举，非法值会立即抛错（fail fast）。
"""

from datetime import date
from typing import Any
from uuid import UUID

from app.agent.models.message import Message, MessageRole
from app.agent.models.run import AgentRun, AgentRunStatus
from app.agent.models.thread import Thread
from app.agent.models.turn import Turn, TurnStatus
from app.coaching.domain.athlete.models import AthleteStateSnapshot, FatigueLevel, RecoveryLevel
from app.coaching.domain.athlete.signals import AthleteStateSignal
from app.coaching.domain.goal.models import GoalStatus, GoalType, TrainingGoal
from app.coaching.domain.plan.models import (
    PlanChange,
    PlanChangePayload,
    PlanChangeStatus,
    PlanChangeType,
    PlannedSession,
    PlanStatus,
    SessionChange,
    SessionType,
    TrainingPlan,
)
from app.coaching.domain.workout.models import Workout, WorkoutFeedback, WorkoutSource, WorkoutType
from app.infrastructure.database.models.agent import AgentRunRow, MessageRow, ThreadRow, TurnRow
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlanChangeRow,
    PlannedSessionRow,
    TrainingGoalRow,
    TrainingPlanRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)


def workout_from_row(row: WorkoutRow) -> Workout:
    return Workout(
        id=row.id,
        user_id=row.user_id,
        started_at=row.started_at,
        distance_m=row.distance_m,
        duration_s=row.duration_s,
        avg_heart_rate=row.avg_heart_rate,
        max_heart_rate=row.max_heart_rate,
        workout_type=WorkoutType(row.workout_type),
        source=WorkoutSource(row.source),
        created_at=row.created_at,
    )


def feedback_from_row(row: WorkoutFeedbackRow) -> WorkoutFeedback:
    return WorkoutFeedback(
        id=row.id,
        user_id=row.user_id,
        workout_id=row.workout_id,
        perceived_exertion=row.perceived_exertion,
        subjective_fatigue=row.subjective_fatigue,
        soreness=row.soreness,
        note=row.note,
        created_at=row.created_at,
    )


def goal_from_row(row: TrainingGoalRow) -> TrainingGoal:
    return TrainingGoal(
        id=row.id,
        user_id=row.user_id,
        goal_type=GoalType(row.goal_type),
        race_date=row.race_date,
        race_distance_m=row.race_distance_m,
        target_time_s=row.target_time_s,
        status=GoalStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def plan_from_row(row: TrainingPlanRow) -> TrainingPlan:
    return TrainingPlan(
        id=row.id,
        user_id=row.user_id,
        version=row.version,
        goal_id=row.goal_id,
        status=PlanStatus(row.status),
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        created_at=row.created_at,
    )


def session_from_row(row: PlannedSessionRow) -> PlannedSession:
    return PlannedSession(
        id=row.id,
        plan_id=row.plan_id,
        scheduled_date=row.scheduled_date,
        session_type=SessionType(row.session_type),
        title=row.title,
        prescription=dict(row.prescription or {}),
    )


def athlete_state_from_row(row: AthleteStateSnapshotRow) -> AthleteStateSnapshot:
    return AthleteStateSnapshot(
        id=row.id,
        user_id=row.user_id,
        version=row.version,
        as_of=row.as_of,
        fatigue_level=FatigueLevel(row.fatigue_level) if row.fatigue_level else None,
        recovery_level=RecoveryLevel(row.recovery_level) if row.recovery_level else None,
        recent_training_load=row.recent_training_load,
        workout_completion_rate=row.workout_completion_rate,
        training_load_coverage=row.training_load_coverage,
        signals=_signals_from_json(row.signals),
        confidence=row.confidence,
        algorithm_version=row.algorithm_version,
        created_at=row.created_at,
    )


def signals_to_json(signals: tuple[AthleteStateSignal, ...]) -> list[dict[str, Any]]:
    return [
        {
            "code": signal.code,
            "severity": signal.severity,
            "message": signal.message,
            "evidence_refs": list(signal.evidence_refs),
        }
        for signal in signals
    ]


def _signals_from_json(raw: list[Any] | None) -> tuple[AthleteStateSignal, ...]:
    if not raw:
        return ()
    return tuple(
        AthleteStateSignal(
            code=item["code"],
            severity=item["severity"],
            message=item["message"],
            evidence_refs=tuple(item.get("evidence_refs") or ()),
        )
        for item in raw
    )


def plan_change_from_row(row: PlanChangeRow) -> PlanChange:
    return PlanChange(
        id=row.id,
        user_id=row.user_id,
        from_plan_id=row.from_plan_id,
        from_plan_version=row.from_plan_version,
        based_on_state_id=row.based_on_state_id,
        based_on_state_version=row.based_on_state_version,
        source_turn_id=row.source_turn_id,
        source_run_id=row.source_run_id,
        as_of=row.as_of,
        change_type=PlanChangeType(row.change_type),
        payload=payload_from_json(row.payload),
        reason=row.reason,
        status=PlanChangeStatus(row.status),
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resulting_plan_id=row.resulting_plan_id,
    )


def payload_from_json(raw: dict[str, Any]) -> PlanChangePayload:
    changes = tuple(
        SessionChange(
            source_session_id=UUID(item["source_session_id"]),
            scheduled_date=date.fromisoformat(item["scheduled_date"]),
            from_type=SessionType(item["from_type"]),
            to_type=SessionType(item["to_type"]),
            old_title=item["old_title"],
            new_title=item["new_title"],
            old_prescription=dict(item.get("old_prescription") or {}),
            new_prescription=dict(item.get("new_prescription") or {}),
        )
        for item in raw.get("changes") or []
    )
    return PlanChangePayload(horizon_days=int(raw["horizon_days"]), changes=changes)


def payload_to_json(payload: PlanChangePayload) -> dict[str, Any]:
    return {
        "horizon_days": payload.horizon_days,
        "changes": [
            {
                "source_session_id": str(change.source_session_id),
                "scheduled_date": change.scheduled_date.isoformat(),
                "from_type": change.from_type.value,
                "to_type": change.to_type.value,
                "old_title": change.old_title,
                "new_title": change.new_title,
                "old_prescription": change.old_prescription,
                "new_prescription": change.new_prescription,
            }
            for change in payload.changes
        ],
    }


def thread_from_row(row: ThreadRow) -> Thread:
    return Thread(
        id=row.id,
        user_id=row.user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def message_from_row(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        thread_id=row.thread_id,
        turn_id=row.turn_id,
        role=MessageRole(row.role),
        content=row.content,
        created_at=row.created_at,
    )


def turn_from_row(row: TurnRow) -> Turn:
    return Turn(
        id=row.id,
        thread_id=row.thread_id,
        user_id=row.user_id,
        user_message_id=row.user_message_id,
        assistant_message_id=row.assistant_message_id,
        status=TurnStatus(row.status),
        started_at=row.started_at,
        committed_at=row.committed_at,
    )


def run_from_row(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        id=row.id,
        turn_id=row.turn_id,
        user_id=row.user_id,
        status=AgentRunStatus(row.status),
        started_at=row.started_at,
        completed_at=row.completed_at,
    )
