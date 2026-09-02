"""Outbox claim / publish 与 consumer receipt 的 PostgreSQL 实现。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.errors import ConflictError, DomainError, NotFoundError
from app.common.events import DurableEventEnvelope, EventMetadata
from app.infrastructure.database.models.outbox import EventConsumptionRow, OutboxEventRow
from app.infrastructure.database.session import short_session


@dataclass(frozen=True)
class ClaimedOutboxEvent:
    """被投递进程认领的一条 outbox 事件快照。"""

    event: DurableEventEnvelope | None  # 解码后的事件；载荷损坏时为 None
    event_id: UUID
    event_type: str
    user_id: UUID
    publish_attempt: int  # 本次是第几次投递尝试
    decode_error: str | None = None  # 事件解码失败时的错误码


class ConsumptionClaim(StrEnum):
    """消费认领的四种结果。"""

    ACQUIRED = "acquired"  # 成功认领，可以处理
    COMPLETED = "completed"  # 已处理完成（幂等去重命中）
    BUSY = "busy"  # 其他实例持有未过期租约
    DEAD_LETTERED = "dead_lettered"  # 已进入死信，不再处理


@dataclass(frozen=True)
class ConsumptionClaimResult:
    """认领结果：结果类型 + 累计尝试次数。"""

    outcome: ConsumptionClaim
    attempt: int


class ConsumptionFailure(StrEnum):
    """消费失败后的两种去向。"""

    RETRY = "retry"  # 可重试，租约释放后再次认领
    DEAD_LETTERED = "dead_lettered"  # 超过重试上限，转入死信


@dataclass(frozen=True)
class ConsumptionFailureResult:
    """失败处理结果：去向 + 累计尝试次数。"""

    outcome: ConsumptionFailure
    attempt: int


class SqlAlchemyOutboxRepository:
    """outbox 仓储：投递进程认领/发布/重试/隔离的实现。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim_pending(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease: timedelta,
        limit: int,
    ) -> tuple[ClaimedOutboxEvent, ...]:
        """认领一批可投递事件：加租约防止多个投递进程重复投递。"""
        async with short_session(self._sessions, commit=True) as session:
            rows = (
                await session.scalars(
                    select(OutboxEventRow)
                    .where(
                        OutboxEventRow.status == "pending",
                        OutboxEventRow.available_at <= now,  # 已到可投递时间
                        (
                            OutboxEventRow.claim_until.is_(None)
                            | (OutboxEventRow.claim_until <= now)
                        ),  # 未被认领，或旧租约已到期
                    )
                    .order_by(OutboxEventRow.created_at.asc(), OutboxEventRow.event_id.asc())
                    .with_for_update(skip_locked=True)  # 已被其他事务锁定的行直接跳过
                    .limit(limit)
                )
            ).all()
            claimed: list[ClaimedOutboxEvent] = []
            for row in rows:
                row.claimed_by = worker_id  # 写入租约：投递窗口内归本进程所有
                row.claim_until = now + lease
                row.publish_attempt_count += 1
                try:
                    event = _event_from_row(row)
                    decode_error = None
                except (DomainError, TypeError, ValueError, AttributeError, KeyError):
                    # 载荷损坏也照常认领，交由上层隔离，避免卡住队列
                    event = None
                    decode_error = "malformed_outbox_event"
                claimed.append(
                    ClaimedOutboxEvent(
                        event=event,
                        event_id=row.event_id,
                        event_type=row.event_type,
                        user_id=row.user_id,
                        publish_attempt=row.publish_attempt_count,
                        decode_error=decode_error,
                    )
                )
            await session.flush()
            return tuple(claimed)

    async def mark_published(
        self, *, event_id: UUID, worker_id: str, published_at: datetime
    ) -> None:
        """投递成功：标记 published 并清空租约。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await self._require_claim(session, event_id=event_id, worker_id=worker_id)
            row.status = "published"
            row.published_at = published_at
            row.claimed_by = None
            row.claim_until = None
            row.last_error_code = None

    async def reschedule(
        self,
        *,
        event_id: UUID,
        worker_id: str,
        available_at: datetime,
        error_code: str,
    ) -> None:
        """投递失败但可重试：推迟到 available_at 再投，释放租约。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await self._require_claim(session, event_id=event_id, worker_id=worker_id)
            row.available_at = available_at
            row.last_error_code = error_code
            row.claimed_by = None
            row.claim_until = None

    async def quarantine(
        self,
        *,
        event_id: UUID,
        worker_id: str,
        quarantined_at: datetime,
        error_code: str,
    ) -> None:
        """投递彻底失败：转入隔离区停止投递，等待人工处理。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await self._require_claim(session, event_id=event_id, worker_id=worker_id)
            row.status = "quarantined"
            row.quarantined_at = quarantined_at
            row.last_error_code = error_code
            row.claimed_by = None
            row.claim_until = None

    async def get(self, *, event_id: UUID) -> DurableEventEnvelope | None:
        """按事件 ID 读取单个事件信封。"""
        async with short_session(self._sessions) as session:
            row = await session.scalar(
                select(OutboxEventRow).where(OutboxEventRow.event_id == event_id)
            )
            return _event_from_row(row) if row is not None else None

    async def list_published_before(
        self, *, cutoff: datetime, limit: int
    ) -> tuple[DurableEventEnvelope, ...]:
        """列出某时间点前已发布的事件（供归档/清理类任务使用）。"""
        async with short_session(self._sessions) as session:
            rows = (
                await session.scalars(
                    select(OutboxEventRow)
                    .where(
                        OutboxEventRow.status == "published",
                        OutboxEventRow.published_at <= cutoff,
                    )
                    .order_by(OutboxEventRow.published_at.asc())
                    .limit(limit)
                )
            ).all()
            return tuple(_event_from_row(row) for row in rows)

    async def list_published_without_terminal_receipt(
        self,
        *,
        consumer_name: str,
        consumer_version: int,
        event_types: tuple[str, ...],
        cutoff: datetime,
        limit: int,
    ) -> tuple[DurableEventEnvelope, ...]:
        """找出已发布但指定消费者尚无终态回执（completed/dead_lettered）的事件。"""
        terminal_receipt = (
            select(EventConsumptionRow.event_id)
            .where(
                EventConsumptionRow.event_id == OutboxEventRow.event_id,
                EventConsumptionRow.consumer_name == consumer_name,
                EventConsumptionRow.consumer_version == consumer_version,
                EventConsumptionRow.status.in_(("completed", "dead_lettered")),
            )
            .exists()
        )
        async with short_session(self._sessions) as session:
            rows = (
                await session.scalars(
                    select(OutboxEventRow)
                    .where(
                        OutboxEventRow.status == "published",
                        OutboxEventRow.published_at <= cutoff,
                        OutboxEventRow.event_type.in_(event_types),
                        ~terminal_receipt,
                    )
                    .order_by(
                        OutboxEventRow.published_at.asc(),
                        OutboxEventRow.event_id.asc(),
                    )
                    .limit(limit)
                )
            ).all()
            return tuple(_event_from_row(row) for row in rows)

    async def _require_claim(
        self, session: AsyncSession, *, event_id: UUID, worker_id: str
    ) -> OutboxEventRow:
        """校验事件仍处于 pending 且租约归本进程；否则视为租约丢失。"""
        row = await session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.event_id == event_id).with_for_update()
        )
        if row is None:
            raise NotFoundError("outbox_event_not_found")
        if row.status != "pending" or row.claimed_by != worker_id:
            raise ConflictError("outbox_claim_lost")  # 租约过期后被他人接管
        return row


class SqlAlchemyConsumptionRepository:
    """consumer receipt 仓储：消费端幂等认领与处理结果记录。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(
        self,
        *,
        consumer_name: str,
        consumer_version: int,
        event_id: UUID,
        user_id: UUID,
        worker_id: str,
        now: datetime,
        lease: timedelta,
    ) -> ConsumptionClaimResult:
        """幂等认领事件：首次创建回执，重复消费按回执状态直接短路。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await session.get(
                EventConsumptionRow,
                (consumer_name, consumer_version, event_id),
                with_for_update=True,  # 锁定回试行，防止并发重复认领
            )
            if row is None:
                # 该事件对该消费者是首次处理：建回执并占用租约
                session.add(
                    EventConsumptionRow(
                        consumer_name=consumer_name,
                        consumer_version=consumer_version,
                        event_id=event_id,
                        user_id=user_id,
                        status="processing",
                        attempt_count=1,
                        lease_owner=worker_id,
                        lease_until=now + lease,
                        last_error_code=None,
                        started_at=now,
                        completed_at=None,
                    )
                )
                return ConsumptionClaimResult(ConsumptionClaim.ACQUIRED, 1)
            if row.user_id != user_id:
                raise ConflictError("event_consumption_user_mismatch")
            if row.status == "completed":
                # 已处理完成：幂等去重命中，不再执行
                return ConsumptionClaimResult(ConsumptionClaim.COMPLETED, row.attempt_count)
            if row.status == "dead_lettered":
                return ConsumptionClaimResult(ConsumptionClaim.DEAD_LETTERED, row.attempt_count)
            if row.lease_until is not None and row.lease_until > now:
                return ConsumptionClaimResult(ConsumptionClaim.BUSY, row.attempt_count)  # 其他实例正在处理
            row.attempt_count += 1  # 租约已过期：重新认领继续重试
            row.lease_owner = worker_id
            row.lease_until = now + lease
            row.last_error_code = None
            return ConsumptionClaimResult(ConsumptionClaim.ACQUIRED, row.attempt_count)

    async def complete(
        self,
        *,
        consumer_name: str,
        consumer_version: int,
        event_id: UUID,
        worker_id: str,
        completed_at: datetime,
    ) -> None:
        """处理成功：回执置为 completed，释放租约。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await self._require_owned(
                session,
                consumer_name=consumer_name,
                consumer_version=consumer_version,
                event_id=event_id,
                worker_id=worker_id,
            )
            row.status = "completed"
            row.completed_at = completed_at
            row.lease_owner = None
            row.lease_until = None
            row.last_error_code = None

    async def fail(
        self,
        *,
        consumer_name: str,
        consumer_version: int,
        event_id: UUID,
        worker_id: str,
        failed_at: datetime,
        error_code: str,
        retryable: bool,
        max_attempts: int,
    ) -> ConsumptionFailureResult:
        """处理失败：未超重试上限则安排重试，否则转入死信。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await self._require_owned(
                session,
                consumer_name=consumer_name,
                consumer_version=consumer_version,
                event_id=event_id,
                worker_id=worker_id,
            )
            row.last_error_code = error_code
            row.lease_owner = None
            row.lease_until = None
            if retryable and row.attempt_count < max_attempts:
                # 还有重试额度：只记错误，不改状态，等下次认领
                return ConsumptionFailureResult(
                    outcome=ConsumptionFailure.RETRY,
                    attempt=row.attempt_count,
                )
            row.status = "dead_lettered"  # 不可重试或重试耗尽：进入死信
            row.completed_at = failed_at
            return ConsumptionFailureResult(
                outcome=ConsumptionFailure.DEAD_LETTERED,
                attempt=row.attempt_count,
            )

    async def is_terminal(
        self, *, consumer_name: str, consumer_version: int, event_id: UUID
    ) -> bool:
        """该事件对该消费者是否已有终态结果（完成或死信）。"""
        async with short_session(self._sessions) as session:
            row = await session.get(
                EventConsumptionRow,
                (consumer_name, consumer_version, event_id),
            )
            return row is not None and row.status in {"completed", "dead_lettered"}

    async def replay(
        self,
        *,
        consumer_name: str,
        consumer_version: int,
        event_id: UUID,
    ) -> None:
        """人工重放：仅允许把死信事件重置回 processing 重新处理。"""
        async with short_session(self._sessions, commit=True) as session:
            row = await session.get(
                EventConsumptionRow,
                (consumer_name, consumer_version, event_id),
                with_for_update=True,
            )
            if row is None:
                raise NotFoundError("event_consumption_not_found")
            if row.status != "dead_lettered":
                raise ConflictError("event_consumption_not_dead_lettered")
            row.status = "processing"
            row.lease_owner = None
            row.lease_until = None
            row.completed_at = None
            row.last_error_code = None

    async def _require_owned(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        consumer_version: int,
        event_id: UUID,
        worker_id: str,
    ) -> EventConsumptionRow:
        """校验回执存在且租约归本进程；否则视为租约丢失。"""
        row = await session.get(
            EventConsumptionRow,
            (consumer_name, consumer_version, event_id),
            with_for_update=True,
        )
        if row is None:
            raise NotFoundError("event_consumption_not_found")
        if row.status != "processing" or row.lease_owner != worker_id:
            raise ConflictError("event_consumption_lease_lost")
        return row


def _event_from_row(row: OutboxEventRow) -> DurableEventEnvelope:
    """outbox Row -> 事件信封（含 correlation/causation/trace 元数据）。"""
    return DurableEventEnvelope(
        event_id=row.event_id,
        event_type=row.event_type,
        schema_version=row.schema_version,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        user_id=row.user_id,
        occurred_at=row.occurred_at,
        payload=dict(row.payload),
        metadata=EventMetadata(
            correlation_id=row.correlation_id,
            causation_id=row.causation_id,
            trace_id=row.trace_id,
        ),
    )
