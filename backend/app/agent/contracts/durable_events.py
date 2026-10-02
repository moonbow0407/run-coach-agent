"""Conversation 终态事实的 durable event v1（跨进程持久化事件合同）。

Turn 提交 / 失败 / 取消后写入事件存储供下游消费；schema 显式校验，
保证事件键与类型严格符合合同，坏数据尽早报错。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.common.errors import DomainError
from app.common.events import DurableEventEnvelope, EventMetadata, EventPayload
from app.common.ids import new_id

# 事件类型名（含 schema 版本号），下游按此路由
TURN_COMMITTED_V1 = "conversation.turn_committed.v1"
TURN_FAILED_V1 = "conversation.turn_failed.v1"
TURN_CANCELLED_V1 = "conversation.turn_cancelled.v1"
AGGREGATE_TYPE = "conversation_turn"  # 聚合类型：事件归属的实体类别
SCHEMA_VERSION = 1  # 事件合同版本，结构变更时递增


@dataclass(frozen=True)
class TurnCommittedV1:
    """turn_committed 事件载荷：一轮对话成功提交的事实。"""

    turn_id: UUID
    thread_id: UUID
    user_message_id: UUID  # 本轮用户消息
    assistant_message_id: UUID  # 本轮助手回复
    run_id: UUID
    committed_at: datetime  # 提交时间


@dataclass(frozen=True)
class TurnTerminalV1:
    """turn failed / cancelled 共用载荷：Turn 进入终态的事实。"""

    turn_id: UUID
    thread_id: UUID
    run_id: UUID
    terminal_at: datetime  # 进入终态的时间


def new_turn_committed_event(
    *,
    user_id: UUID,
    payload: TurnCommittedV1,
    metadata: EventMetadata,
) -> DurableEventEnvelope:
    """构造 turn_committed 事件信封。"""
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
    """构造 turn failed / cancelled 事件信封。"""
    # 终态只允许这两种事件类型，其它请求直接拒绝
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
    """校验并解码 turn_committed 事件信封为结构化载荷。"""
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
    # 聚合 ID / 发生时间必须与载荷一致，防止事件被错位投递或篡改
    if payload.turn_id != event.aggregate_id or payload.committed_at != event.occurred_at:
        raise DomainError("durable_event_identity_mismatch")
    return payload


def decode_turn_terminal(event: DurableEventEnvelope) -> TurnTerminalV1:
    """校验并解码 turn failed / cancelled 事件信封为结构化载荷。"""
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
    # 聚合 ID / 发生时间必须与载荷一致，防止事件被错位投递或篡改
    if payload.turn_id != event.aggregate_id or payload.terminal_at != event.occurred_at:
        raise DomainError("durable_event_identity_mismatch")
    return payload


def validate_agent_event(event: DurableEventEnvelope) -> None:
    """校验本模块定义的任意 agent 事件；不识别的类型直接报错。"""
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
    """填充公共信封字段，构造标准事件。"""
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
    """校验事件类型 / schema 版本 / 聚合类型是否与本合同匹配。"""
    if (
        event.event_type != event_type
        or event.schema_version != SCHEMA_VERSION
        or event.aggregate_type != AGGREGATE_TYPE
    ):
        raise DomainError("unsupported_agent_event_schema")


def _require_keys(payload: EventPayload, expected: set[str]) -> None:
    """payload 键必须与期望完全一致（多键或少键都算非法事件）。"""
    if set(payload) != expected:
        raise DomainError("invalid_agent_event_payload")


def _uuid(payload: EventPayload, key: str) -> UUID:
    """从 payload 取出并解析 UUID 字符串，格式非法即报错。"""
    value = payload.get(key)
    if not isinstance(value, str):
        raise DomainError("invalid_agent_event_payload")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainError("invalid_agent_event_payload") from exc


def _datetime(payload: EventPayload, key: str) -> datetime:
    """解析 ISO 时间字符串；必须带时区，避免跨进程时间语义歧义。"""
    value = payload.get(key)
    if not isinstance(value, str):
        raise DomainError("invalid_agent_event_payload")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DomainError("invalid_agent_event_payload") from exc
    # 缺时区的时间无法确定绝对时刻，视为非法
    if moment.tzinfo is None:
        raise DomainError("invalid_agent_event_payload")
    return moment
