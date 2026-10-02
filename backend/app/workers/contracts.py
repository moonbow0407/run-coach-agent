"""Provider-neutral Worker task envelope 与 JSON codec。

定义投递到 arq 队列的任务信封结构，及其与 JSON 字典互转的严格编解码。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.common.errors import DomainError
from app.common.events import DurableEventEnvelope, EventMetadata, JsonValue

TASK_VERSION = 1  # 任务契约版本：路由与消费都校验此版本，防止新旧格式混跑


@dataclass(frozen=True)
class WorkerTaskEnvelope:
    """投递到队列的最小任务单元：任务名 + 契约版本 + 一个持久化事件。

    dataclass(frozen=True)：不可变数据类，信封在传递途中不允许被修改。
    """

    task_name: str  # 消费者任务名（对应 handler 注册表）
    task_version: int  # 任务契约版本
    event: DurableEventEnvelope  # 触发本次任务的持久化事件（durable event）
    enqueued_at: datetime  # 入队时间（必须带时区），用于追踪与恢复判断

    def __post_init__(self) -> None:
        # 构造期即校验（fail fast）：非法任务在入队前就暴露。
        if not self.task_name or len(self.task_name) > 100:
            raise DomainError("invalid_worker_task_name")
        if self.task_version <= 0:
            raise DomainError("invalid_worker_task_version")
        if self.enqueued_at.tzinfo is None:
            raise DomainError("worker_task_enqueued_at_requires_timezone")

    @property
    def job_id(self) -> str:
        """队列任务唯一 ID：同事件同任务在队列中天然去重。"""
        return f"{self.task_name}:{self.task_version}:{self.event.event_id}"

    def to_dict(self) -> dict[str, JsonValue]:
        """序列化为队列 JSON 载荷；键集与 from_dict 严格对齐。"""
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
        """从队列 JSON 还原信封：键集与类型逐一严格校验，任何不一致都拒绝。"""
        # 顶层键必须完全一致：多字段 / 少字段都拒绝，防止数据被静默丢弃。
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
        # 事件子对象的键集同样要求完全匹配。
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
    """取非空字符串字段；缺失或类型不对即报错。"""
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise DomainError("invalid_worker_task_payload")
    return value


def _uuid(raw: dict[str, object], key: str) -> UUID:
    """取必填 UUID 字段，格式不合法即报错。"""
    try:
        return UUID(_string(raw, key))
    except ValueError as exc:
        raise DomainError("invalid_worker_task_payload") from exc


def _optional_uuid(value: object) -> UUID | None:
    """取可选 UUID 字段：缺省为 None，给了就必须合法。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainError("invalid_worker_task_payload")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainError("invalid_worker_task_payload") from exc


def _datetime(raw: dict[str, object], key: str) -> datetime:
    """取带时区的 ISO 时间字段；无时区视为非法。"""
    try:
        moment = datetime.fromisoformat(_string(raw, key))
    except ValueError as exc:
        raise DomainError("invalid_worker_task_payload") from exc
    # 无时区的时间无法与数据库时间可靠比较，直接拒绝。
    if moment.tzinfo is None:
        raise DomainError("invalid_worker_task_payload")
    return moment
