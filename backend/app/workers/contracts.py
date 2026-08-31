"""Provider-neutral Worker task envelope 与 JSON codec。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.common.errors import DomainError
from app.common.events import DurableEventEnvelope, EventMetadata, JsonValue

TASK_VERSION = 1


@dataclass(frozen=True)
class WorkerTaskEnvelope:
    task_name: str
    task_version: int
    event: DurableEventEnvelope
    enqueued_at: datetime

    def __post_init__(self) -> None:
        if not self.task_name or len(self.task_name) > 100:
            raise DomainError("invalid_worker_task_name")
        if self.task_version <= 0:
            raise DomainError("invalid_worker_task_version")
        if self.enqueued_at.tzinfo is None:
            raise DomainError("worker_task_enqueued_at_requires_timezone")

    @property
    def job_id(self) -> str:
        return f"{self.task_name}:{self.task_version}:{self.event.event_id}"

    def to_dict(self) -> dict[str, JsonValue]:
        event = self.event
        return {
            "task_name": self.task_name,
            "task_version": self.task_version,
            "enqueued_at": self.enqueued_at.isoformat(),
            "event": {
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "schema_version": event.schema_version,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "user_id": str(event.user_id),
                "occurred_at": event.occurred_at.isoformat(),
                "payload": event.payload,
                "correlation_id": str(event.metadata.correlation_id),
                "causation_id": (
                    str(event.metadata.causation_id)
                    if event.metadata.causation_id is not None
                    else None
                ),
                "trace_id": (
                    str(event.metadata.trace_id) if event.metadata.trace_id is not None else None
                ),
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "WorkerTaskEnvelope":
        if set(raw) != {"task_name", "task_version", "enqueued_at", "event"}:
            raise DomainError("invalid_worker_task_payload")
        event_raw = raw.get("event")
        if not isinstance(event_raw, dict):
            raise DomainError("invalid_worker_task_payload")
        expected_event_keys = {
            "event_id",
            "event_type",
            "schema_version",
            "aggregate_type",
            "aggregate_id",
            "user_id",
            "occurred_at",
            "payload",
            "correlation_id",
            "causation_id",
            "trace_id",
        }
        if set(event_raw) != expected_event_keys:
            raise DomainError("invalid_worker_task_payload")
        payload = event_raw.get("payload")
        if not isinstance(payload, dict):
            raise DomainError("invalid_worker_task_payload")
        task_version = raw.get("task_version")
        schema_version = event_raw.get("schema_version")
        if not isinstance(task_version, int) or not isinstance(schema_version, int):
            raise DomainError("invalid_worker_task_payload")
        event = DurableEventEnvelope(
            event_id=_uuid(event_raw, "event_id"),
            event_type=_string(event_raw, "event_type"),
            schema_version=schema_version,
            aggregate_type=_string(event_raw, "aggregate_type"),
            aggregate_id=_uuid(event_raw, "aggregate_id"),
            user_id=_uuid(event_raw, "user_id"),
            occurred_at=_datetime(event_raw, "occurred_at"),
            payload=payload,  # type: ignore[arg-type]
            metadata=EventMetadata(
                correlation_id=_uuid(event_raw, "correlation_id"),
                causation_id=_optional_uuid(event_raw.get("causation_id")),
                trace_id=_optional_uuid(event_raw.get("trace_id")),
            ),
        )
        return cls(
            task_name=_string(raw, "task_name"),
            task_version=task_version,
            event=event,
            enqueued_at=_datetime(raw, "enqueued_at"),
        )


def _string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise DomainError("invalid_worker_task_payload")
    return value


def _uuid(raw: dict[str, object], key: str) -> UUID:
    try:
        return UUID(_string(raw, key))
    except ValueError as exc:
        raise DomainError("invalid_worker_task_payload") from exc


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainError("invalid_worker_task_payload")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainError("invalid_worker_task_payload") from exc


def _datetime(raw: dict[str, object], key: str) -> datetime:
    try:
        moment = datetime.fromisoformat(_string(raw, key))
    except ValueError as exc:
        raise DomainError("invalid_worker_task_payload") from exc
    if moment.tzinfo is None:
        raise DomainError("invalid_worker_task_payload")
    return moment
