"""Conversation terminal facts 的 durable event v1。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.common.errors import DomainError
from app.common.events import DurableEventEnvelope, EventMetadata, EventPayload
from app.common.ids import new_id

TURN_COMMITTED_V1 = "conversation.turn_committed.v1"
TURN_FAILED_V1 = "conversation.turn_failed.v1"
TURN_CANCELLED_V1 = "conversation.turn_cancelled.v1"
AGGREGATE_TYPE = "conversation_turn"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TurnCommittedV1:
    turn_id: UUID
    thread_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    run_id: UUID
    committed_at: datetime


@dataclass(frozen=True)
class TurnTerminalV1:
    turn_id: UUID
    thread_id: UUID
    run_id: UUID
    terminal_at: datetime


def new_turn_committed_event(
    *,
    user_id: UUID,
    payload: TurnCommittedV1,
    metadata: EventMetadata,
) -> DurableEventEnvelope:
    return _event(
        event_type=TURN_COMMITTED_V1,
        user_id=user_id,
        turn_id=payload.turn_id,
        occurred_at=payload.committed_at,
        payload={
            "turn_id": str(payload.turn_id),
            "thread_id": str(payload.thread_id),
            "user_message_id": str(payload.user_message_id),
            "assistant_message_id": str(payload.assistant_message_id),
            "run_id": str(payload.run_id),
            "committed_at": payload.committed_at.isoformat(),
        },
        metadata=metadata,
    )


def new_turn_terminal_event(
    *,
    event_type: str,
    user_id: UUID,
    payload: TurnTerminalV1,
    metadata: EventMetadata,
) -> DurableEventEnvelope:
    if event_type not in {TURN_FAILED_V1, TURN_CANCELLED_V1}:
        raise DomainError("invalid_terminal_turn_event_type")
    return _event(
        event_type=event_type,
        user_id=user_id,
        turn_id=payload.turn_id,
        occurred_at=payload.terminal_at,
        payload={
            "turn_id": str(payload.turn_id),
            "thread_id": str(payload.thread_id),
            "run_id": str(payload.run_id),
            "terminal_at": payload.terminal_at.isoformat(),
        },
        metadata=metadata,
    )


def decode_turn_committed(event: DurableEventEnvelope) -> TurnCommittedV1:
    _validate_envelope(event, TURN_COMMITTED_V1)
    _require_keys(
        event.payload,
        {
            "turn_id",
            "thread_id",
            "user_message_id",
            "assistant_message_id",
            "run_id",
            "committed_at",
        },
    )
    payload = TurnCommittedV1(
        turn_id=_uuid(event.payload, "turn_id"),
        thread_id=_uuid(event.payload, "thread_id"),
        user_message_id=_uuid(event.payload, "user_message_id"),
        assistant_message_id=_uuid(event.payload, "assistant_message_id"),
        run_id=_uuid(event.payload, "run_id"),
        committed_at=_datetime(event.payload, "committed_at"),
    )
    if payload.turn_id != event.aggregate_id or payload.committed_at != event.occurred_at:
        raise DomainError("durable_event_identity_mismatch")
    return payload


def decode_turn_terminal(event: DurableEventEnvelope) -> TurnTerminalV1:
    if event.event_type not in {TURN_FAILED_V1, TURN_CANCELLED_V1}:
        raise DomainError("unsupported_terminal_turn_event")
    _validate_envelope(event, event.event_type)
    _require_keys(event.payload, {"turn_id", "thread_id", "run_id", "terminal_at"})
    payload = TurnTerminalV1(
        turn_id=_uuid(event.payload, "turn_id"),
        thread_id=_uuid(event.payload, "thread_id"),
        run_id=_uuid(event.payload, "run_id"),
        terminal_at=_datetime(event.payload, "terminal_at"),
    )
    if payload.turn_id != event.aggregate_id or payload.terminal_at != event.occurred_at:
        raise DomainError("durable_event_identity_mismatch")
    return payload


def validate_agent_event(event: DurableEventEnvelope) -> None:
    if event.event_type == TURN_COMMITTED_V1:
        decode_turn_committed(event)
    elif event.event_type in {TURN_FAILED_V1, TURN_CANCELLED_V1}:
        decode_turn_terminal(event)
    else:
        raise DomainError("unsupported_agent_event_schema")


def _event(
    *,
    event_type: str,
    user_id: UUID,
    turn_id: UUID,
    occurred_at: datetime,
    payload: EventPayload,
    metadata: EventMetadata,
) -> DurableEventEnvelope:
    return DurableEventEnvelope(
        event_id=new_id(),
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=turn_id,
        user_id=user_id,
        occurred_at=occurred_at,
        payload=payload,
        metadata=metadata,
    )


def _validate_envelope(event: DurableEventEnvelope, event_type: str) -> None:
    if (
        event.event_type != event_type
        or event.schema_version != SCHEMA_VERSION
        or event.aggregate_type != AGGREGATE_TYPE
    ):
        raise DomainError("unsupported_agent_event_schema")


def _require_keys(payload: EventPayload, expected: set[str]) -> None:
    if set(payload) != expected:
        raise DomainError("invalid_agent_event_payload")


def _uuid(payload: EventPayload, key: str) -> UUID:
    value = payload.get(key)
    if not isinstance(value, str):
        raise DomainError("invalid_agent_event_payload")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainError("invalid_agent_event_payload") from exc


def _datetime(payload: EventPayload, key: str) -> datetime:
    value = payload.get(key)
    if not isinstance(value, str):
        raise DomainError("invalid_agent_event_payload")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DomainError("invalid_agent_event_payload") from exc
    if moment.tzinfo is None:
        raise DomainError("invalid_agent_event_payload")
    return moment
