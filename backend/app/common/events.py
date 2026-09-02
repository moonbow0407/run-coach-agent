"""Durable Business Event 的最小跨模块合同。

这里不提供通用 Event Bus。Envelope 只承载稳定 identity、可信追踪元数据与
versioned payload；具体 payload 仍由事实所属的 agent / coaching 模块定义。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.common.errors import DomainError

# type 别名（PEP 695 语法）：只给类型起业务名字，运行时与原类型完全等价。
type JsonPrimitive = str | int | float | bool | None  # JSON 标量值
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]  # 任意可 JSON 化的值（递归定义）
type EventPayload = dict[str, JsonValue]  # 事件负载：字符串键到 JSON 值的字典


@dataclass(frozen=True)  # frozen：不可变数据类，实例创建后禁止就地修改
class EventMetadata:
    """由可信入口创建并随 canonical transaction 写入的关联元数据。"""

    correlation_id: UUID  # 关联 ID：串起同一次业务流程产生的所有事件
    causation_id: UUID | None = None  # 因果 ID：直接触发本事件的上游事件/消息 ID
    trace_id: UUID | None = None  # 追踪 ID：跨模块全链路排查用


@dataclass(frozen=True)
class DurableEventEnvelope:
    """Provider-neutral durable event；不包含 ORM、模型文本或队列字段。"""

    event_id: UUID  # 事件全局唯一标识
    event_type: str  # 事件类型名，消费方据此路由与解析
    schema_version: int  # payload 结构版本号，消费方据此做兼容解析
    aggregate_type: str  # 事件所属领域对象（聚合）的类型名
    aggregate_id: UUID  # 事件所属领域对象的 ID
    user_id: UUID  # 事件归属的用户
    occurred_at: datetime  # 业务事实发生时刻（带时区），非落库时间
    payload: EventPayload  # 事件业务数据，结构随 schema_version 演进
    metadata: EventMetadata  # 可信追踪元数据

    # dataclass 钩子：实例构造完成后立即执行，用于对信封做 fail-fast 校验。
    def __post_init__(self) -> None:
        # 事件类型名是消费方路由的依据，必须非空且长度可控。
        if not self.event_type or len(self.event_type) > 120:
            raise DomainError("invalid_durable_event_type")
        # 版本号必须为正整数，否则消费方无法按契约解析 payload。
        if self.schema_version <= 0:
            raise DomainError("invalid_durable_event_schema_version")
        # 聚合类型名同样需要非空且长度受限，保证跨模块可读可存储。
        if not self.aggregate_type or len(self.aggregate_type) > 80:
            raise DomainError("invalid_durable_event_aggregate_type")
        # 无时区的时间无法与 UTC 事件流对齐排序，直接拒绝。
        if self.occurred_at.tzinfo is None:
            raise DomainError("durable_event_occurred_at_requires_timezone")
