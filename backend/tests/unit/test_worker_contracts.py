"""Phase 5 只覆盖非平凡的 schema/routing 与 retry 确定性逻辑。"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.agent.contracts.durable_events import (
    TURN_CANCELLED_V1,
    TURN_COMMITTED_V1,
    TURN_FAILED_V1,
    TurnCommittedV1,
    TurnTerminalV1,
    new_turn_committed_event,
    new_turn_terminal_event,
)
from app.coaching.contracts.durable_events import (
    ATHLETE_STATE_RECOMPUTED_V1,
    PLAN_CHANGE_CONFIRMED_V1,
    AthleteStateRecomputedV1,
    ChangeKind,
    PlanChangeConfirmedV1,
    WorkoutChangedV1,
    WorkoutFeedbackChangedV1,
    new_athlete_state_recomputed_event,
    new_plan_change_confirmed_event,
    new_workout_changed_event,
    new_workout_feedback_changed_event,
)
from app.common.errors import DomainError
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.workers.contracts import WorkerTaskEnvelope
from app.workers.retry import RETRY_DELAYS, retry_delay
from app.workers.routing import (
    FINALIZE_TERMINAL_TURN,
    PROJECT_EPISODE,
    PROJECT_SEMANTIC_MEMORY,
    RECOMPUTE_ATHLETE_STATE,
    route_event,
)

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def test_all_seven_event_schemas_have_fixed_v1_routes() -> None:
    routes = {
        event.event_type: tuple(task.task_name for task in route_event(event, enqueued_at=NOW))
        for event in _events()
    }
    assert routes == {
        TURN_COMMITTED_V1: (FINALIZE_TERMINAL_TURN, PROJECT_SEMANTIC_MEMORY),
        TURN_FAILED_V1: (FINALIZE_TERMINAL_TURN,),
        TURN_CANCELLED_V1: (FINALIZE_TERMINAL_TURN,),
        "coaching.workout_changed.v1": (RECOMPUTE_ATHLETE_STATE,),
        "coaching.workout_feedback_changed.v1": (RECOMPUTE_ATHLETE_STATE,),
        ATHLETE_STATE_RECOMPUTED_V1: (PROJECT_EPISODE,),
        PLAN_CHANGE_CONFIRMED_V1: (PROJECT_EPISODE,),
    }


def test_task_codec_is_strict_and_schema_version_mismatch_is_rejected() -> None:
    task = route_event(_events()[0], enqueued_at=NOW)[0]
    assert WorkerTaskEnvelope.from_dict(task.to_dict()) == task
    malformed = task.to_dict()
    malformed["unexpected"] = True
    with pytest.raises(DomainError, match="invalid_worker_task_payload"):
        WorkerTaskEnvelope.from_dict(malformed)
    with pytest.raises(DomainError, match="unsupported_.*event_schema"):
        route_event(replace(task.event, schema_version=2), enqueued_at=NOW)


def test_retry_schedule_is_deterministic_and_bounded() -> None:
    event_id = new_id()
    first = retry_delay(attempt=1, event_id=event_id)
    assert first == retry_delay(attempt=1, event_id=event_id)
    assert RETRY_DELAYS[0] <= first <= RETRY_DELAYS[0] * 1.2
    capped = retry_delay(attempt=100, event_id=event_id)
    assert RETRY_DELAYS[-1] <= capped <= RETRY_DELAYS[-1] * 1.2


def _events():
    user_id = new_id()
    metadata = EventMetadata(correlation_id=new_id(), trace_id=new_id())
    turn_id = new_id()
    workout_id = new_id()
    feedback_id = new_id()
    snapshot_id = new_id()
    plan_change_id = new_id()
    return (
        new_turn_committed_event(
            user_id=user_id,
            payload=TurnCommittedV1(
                turn_id=turn_id,
                thread_id=new_id(),
                user_message_id=new_id(),
                assistant_message_id=new_id(),
                run_id=new_id(),
                committed_at=NOW,
            ),
            metadata=metadata,
        ),
        new_turn_terminal_event(
            event_type=TURN_FAILED_V1,
            user_id=user_id,
            payload=TurnTerminalV1(turn_id, new_id(), new_id(), NOW),
            metadata=metadata,
        ),
        new_turn_terminal_event(
            event_type=TURN_CANCELLED_V1,
            user_id=user_id,
            payload=TurnTerminalV1(turn_id, new_id(), new_id(), NOW),
            metadata=metadata,
        ),
        new_workout_changed_event(
            user_id=user_id,
            payload=WorkoutChangedV1(workout_id, ChangeKind.RECORDED, NOW, NOW),
            metadata=metadata,
        ),
        new_workout_feedback_changed_event(
            user_id=user_id,
            payload=WorkoutFeedbackChangedV1(
                feedback_id,
                workout_id,
                ChangeKind.RECORDED,
                NOW,
                NOW,
            ),
            metadata=metadata,
        ),
        new_athlete_state_recomputed_event(
            user_id=user_id,
            payload=AthleteStateRecomputedV1(snapshot_id, 1, NOW, "phase3.v1"),
            metadata=metadata,
        ),
        new_plan_change_confirmed_event(
            user_id=user_id,
            payload=PlanChangeConfirmedV1(
                plan_change_id,
                new_id(),
                new_id(),
                snapshot_id,
                NOW,
            ),
            metadata=metadata,
        ),
    )
