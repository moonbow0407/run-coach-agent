"""Coaching canonical changes 的 durable event v1。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.common.errors import DomainError
from app.common.events import DurableEventEnvelope, EventMetadata, EventPayload
from app.common.ids import new_id

WORKOUT_CHANGED_V1 = "coaching.workout_changed.v1"
WORKOUT_FEEDBACK_CHANGED_V1 = "coaching.workout_feedback_changed.v1"
ATHLETE_STATE_RECOMPUTED_V1 = "coaching.athlete_state_recomputed.v1"
PLAN_CHANGE_CONFIRMED_V1 = "coaching.plan_change_confirmed.v1"
SCHEMA_VERSION = 1


class ChangeKind(StrEnum):
    RECORDED = "recorded"
    UPDATED = "updated"


@dataclass(frozen=True)
class WorkoutChangedV1:
    workout_id: UUID
    change_kind: ChangeKind
    source_fact_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class WorkoutFeedbackChangedV1:
    feedback_id: UUID
    workout_id: UUID
    change_kind: ChangeKind
    source_fact_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class AthleteStateRecomputedV1:
    snapshot_id: UUID
    snapshot_version: int
    as_of: datetime
    algorithm_version: str


@dataclass(frozen=True)
class PlanChangeConfirmedV1:
    plan_change_id: UUID
    from_plan_id: UUID
    resulting_plan_id: UUID
    based_on_state_id: UUID
    confirmed_at: datetime


def new_workout_changed_event(
    *, user_id: UUID, payload: WorkoutChangedV1, metadata: EventMetadata
) -> DurableEventEnvelope:
    return _event(
        event_type=WORKOUT_CHANGED_V1,
        aggregate_type="workout",
        aggregate_id=payload.workout_id,
        user_id=user_id,
        occurred_at=payload.available_at,
        payload={
            "workout_id": str(payload.workout_id),
            "change_kind": payload.change_kind.value,
            "source_fact_at": payload.source_fact_at.isoformat(),
            "available_at": payload.available_at.isoformat(),
        },
        metadata=metadata,
    )


def new_workout_feedback_changed_event(
    *, user_id: UUID, payload: WorkoutFeedbackChangedV1, metadata: EventMetadata
) -> DurableEventEnvelope:
    return _event(
        event_type=WORKOUT_FEEDBACK_CHANGED_V1,
        aggregate_type="workout_feedback",
        aggregate_id=payload.feedback_id,
        user_id=user_id,
        occurred_at=payload.available_at,
        payload={
            "feedback_id": str(payload.feedback_id),
            "workout_id": str(payload.workout_id),
            "change_kind": payload.change_kind.value,
            "source_fact_at": payload.source_fact_at.isoformat(),
            "available_at": payload.available_at.isoformat(),
        },
        metadata=metadata,
    )


def new_athlete_state_recomputed_event(
    *, user_id: UUID, payload: AthleteStateRecomputedV1, metadata: EventMetadata
) -> DurableEventEnvelope:
    return _event(
        event_type=ATHLETE_STATE_RECOMPUTED_V1,
        aggregate_type="athlete_state_snapshot",
        aggregate_id=payload.snapshot_id,
        user_id=user_id,
        occurred_at=payload.as_of,
        payload={
            "snapshot_id": str(payload.snapshot_id),
            "snapshot_version": payload.snapshot_version,
            "as_of": payload.as_of.isoformat(),
            "algorithm_version": payload.algorithm_version,
        },
        metadata=metadata,
    )


def new_plan_change_confirmed_event(
    *, user_id: UUID, payload: PlanChangeConfirmedV1, metadata: EventMetadata
) -> DurableEventEnvelope:
    return _event(
        event_type=PLAN_CHANGE_CONFIRMED_V1,
        aggregate_type="plan_change",
        aggregate_id=payload.plan_change_id,
        user_id=user_id,
        occurred_at=payload.confirmed_at,
        payload={
            "plan_change_id": str(payload.plan_change_id),
            "from_plan_id": str(payload.from_plan_id),
            "resulting_plan_id": str(payload.resulting_plan_id),
            "based_on_state_id": str(payload.based_on_state_id),
            "confirmed_at": payload.confirmed_at.isoformat(),
        },
        metadata=metadata,
    )


def decode_workout_changed(event: DurableEventEnvelope) -> WorkoutChangedV1:
    validate_coaching_event(event)
    if event.event_type != WORKOUT_CHANGED_V1:
        raise DomainError("unsupported_workout_changed_event")
    return WorkoutChangedV1(
        workout_id=_uuid(event.payload, "workout_id"),
        change_kind=_change_kind(event.payload),
        source_fact_at=_datetime(event.payload, "source_fact_at"),
        available_at=_datetime(event.payload, "available_at"),
    )


def decode_workout_feedback_changed(
    event: DurableEventEnvelope,
) -> WorkoutFeedbackChangedV1:
    validate_coaching_event(event)
    if event.event_type != WORKOUT_FEEDBACK_CHANGED_V1:
        raise DomainError("unsupported_workout_feedback_changed_event")
    return WorkoutFeedbackChangedV1(
        feedback_id=_uuid(event.payload, "feedback_id"),
        workout_id=_uuid(event.payload, "workout_id"),
        change_kind=_change_kind(event.payload),
        source_fact_at=_datetime(event.payload, "source_fact_at"),
        available_at=_datetime(event.payload, "available_at"),
    )


def decode_athlete_state_recomputed(
    event: DurableEventEnvelope,
) -> AthleteStateRecomputedV1:
    validate_coaching_event(event)
    if event.event_type != ATHLETE_STATE_RECOMPUTED_V1:
        raise DomainError("unsupported_athlete_state_event")
    version = event.payload.get("snapshot_version")
    if not isinstance(version, int):
        raise DomainError("invalid_coaching_event_payload")
    return AthleteStateRecomputedV1(
        snapshot_id=_uuid(event.payload, "snapshot_id"),
        snapshot_version=version,
        as_of=_datetime(event.payload, "as_of"),
        algorithm_version=_string(event.payload, "algorithm_version"),
    )


def decode_plan_change_confirmed(event: DurableEventEnvelope) -> PlanChangeConfirmedV1:
    validate_coaching_event(event)
    if event.event_type != PLAN_CHANGE_CONFIRMED_V1:
        raise DomainError("unsupported_plan_change_event")
    return PlanChangeConfirmedV1(
        plan_change_id=_uuid(event.payload, "plan_change_id"),
        from_plan_id=_uuid(event.payload, "from_plan_id"),
        resulting_plan_id=_uuid(event.payload, "resulting_plan_id"),
        based_on_state_id=_uuid(event.payload, "based_on_state_id"),
        confirmed_at=_datetime(event.payload, "confirmed_at"),
    )


def validate_coaching_event(event: DurableEventEnvelope) -> None:
    expected = _SCHEMAS.get(event.event_type)
    if expected is None:
        raise DomainError("unsupported_coaching_event_schema")
    aggregate_type, keys = expected
    if (
        event.schema_version != SCHEMA_VERSION
        or event.aggregate_type != aggregate_type
        or set(event.payload) != keys
    ):
        raise DomainError("unsupported_coaching_event_schema")
    identity_key = {
        WORKOUT_CHANGED_V1: "workout_id",
        WORKOUT_FEEDBACK_CHANGED_V1: "feedback_id",
        ATHLETE_STATE_RECOMPUTED_V1: "snapshot_id",
        PLAN_CHANGE_CONFIRMED_V1: "plan_change_id",
    }[event.event_type]
    if _uuid(event.payload, identity_key) != event.aggregate_id:
        raise DomainError("durable_event_identity_mismatch")
    if event.event_type in {WORKOUT_CHANGED_V1, WORKOUT_FEEDBACK_CHANGED_V1}:
        _change_kind(event.payload)
        available_at = _datetime(event.payload, "available_at")
        _datetime(event.payload, "source_fact_at")
        if available_at != event.occurred_at:
            raise DomainError("durable_event_identity_mismatch")
    elif event.event_type == ATHLETE_STATE_RECOMPUTED_V1:
        version = event.payload.get("snapshot_version")
        if not isinstance(version, int) or version <= 0:
            raise DomainError("invalid_coaching_event_payload")
        if _datetime(event.payload, "as_of") != event.occurred_at:
            raise DomainError("durable_event_identity_mismatch")
        _string(event.payload, "algorithm_version")
    else:
        _uuid(event.payload, "from_plan_id")
        _uuid(event.payload, "resulting_plan_id")
        _uuid(event.payload, "based_on_state_id")
        if _datetime(event.payload, "confirmed_at") != event.occurred_at:
            raise DomainError("durable_event_identity_mismatch")


_SCHEMAS: dict[str, tuple[str, set[str]]] = {
    WORKOUT_CHANGED_V1: (
        "workout",
        {"workout_id", "change_kind", "source_fact_at", "available_at"},
    ),
    WORKOUT_FEEDBACK_CHANGED_V1: (
        "workout_feedback",
        {"feedback_id", "workout_id", "change_kind", "source_fact_at", "available_at"},
    ),
    ATHLETE_STATE_RECOMPUTED_V1: (
        "athlete_state_snapshot",
        {"snapshot_id", "snapshot_version", "as_of", "algorithm_version"},
    ),
    PLAN_CHANGE_CONFIRMED_V1: (
        "plan_change",
        {
            "plan_change_id",
            "from_plan_id",
            "resulting_plan_id",
            "based_on_state_id",
            "confirmed_at",
        },
    ),
}


def _event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    user_id: UUID,
    occurred_at: datetime,
    payload: EventPayload,
    metadata: EventMetadata,
) -> DurableEventEnvelope:
    return DurableEventEnvelope(
        event_id=new_id(),
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        user_id=user_id,
        occurred_at=occurred_at,
        payload=payload,
        metadata=metadata,
    )


def _change_kind(payload: EventPayload) -> ChangeKind:
    try:
        return ChangeKind(_string(payload, "change_kind"))
    except ValueError as exc:
        raise DomainError("invalid_coaching_event_payload") from exc


def _string(payload: EventPayload, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DomainError("invalid_coaching_event_payload")
    return value


def _uuid(payload: EventPayload, key: str) -> UUID:
    try:
        return UUID(_string(payload, key))
    except ValueError as exc:
        raise DomainError("invalid_coaching_event_payload") from exc


def _datetime(payload: EventPayload, key: str) -> datetime:
    try:
        moment = datetime.fromisoformat(_string(payload, key))
    except ValueError as exc:
        raise DomainError("invalid_coaching_event_payload") from exc
    if moment.tzinfo is None:
        raise DomainError("invalid_coaching_event_payload")
    return moment
