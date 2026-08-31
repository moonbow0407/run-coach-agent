"""Durable Business Event 的最小跨模块合同。

这里不提供通用 Event Bus。Envelope 只承载稳定 identity、可信追踪元数据与
versioned payload；具体 payload 仍由事实所属的 agent / coaching 模块定义。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.common.errors import DomainError

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type EventPayload = dict[str, JsonValue]


@dataclass(frozen=True)
class EventMetadata:
    """由可信入口创建并随 canonical transaction 写入的关联元数据。"""

    correlation_id: UUID
    causation_id: UUID | None = None
    trace_id: UUID | None = None


@dataclass(frozen=True)
class DurableEventEnvelope:
    """Provider-neutral durable event；不包含 ORM、模型文本或队列字段。"""

    event_id: UUID
    event_type: str
    schema_version: int
    aggregate_type: str
    aggregate_id: UUID
    user_id: UUID
    occurred_at: datetime
    payload: EventPayload
    metadata: EventMetadata

    def __post_init__(self) -> None:
        if not self.event_type or len(self.event_type) > 120:
            raise DomainError("invalid_durable_event_type")
        if self.schema_version <= 0:
            raise DomainError("invalid_durable_event_schema_version")
        if not self.aggregate_type or len(self.aggregate_type) > 80:
            raise DomainError("invalid_durable_event_aggregate_type")
        if self.occurred_at.tzinfo is None:
            raise DomainError("durable_event_occurred_at_requires_timezone")
