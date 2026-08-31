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
    event: DurableEventEnvelope | None
    event_id: UUID
    event_type: str
    user_id: UUID
    publish_attempt: int
    decode_error: str | None = None


class ConsumptionClaim(StrEnum):
    ACQUIRED = "acquired"
    COMPLETED = "completed"
    BUSY = "busy"
    DEAD_LETTERED = "dead_lettered"


@dataclass(frozen=True)
class ConsumptionClaimResult:
    outcome: ConsumptionClaim
    attempt: int


class ConsumptionFailure(StrEnum):
    RETRY = "retry"
    DEAD_LETTERED = "dead_lettered"


@dataclass(frozen=True)
class ConsumptionFailureResult:
    outcome: ConsumptionFailure
    attempt: int


class SqlAlchemyOutboxRepository:
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
        async with short_session(self._sessions, commit=True) as session:
            rows = (
                await session.scalars(
                    select(OutboxEventRow)
                    .where(
                        OutboxEventRow.status == "pending",
                        OutboxEventRow.available_at <= now,
                        (
                            OutboxEventRow.claim_until.is_(None)
                            | (OutboxEventRow.claim_until <= now)
                        ),
                    )
                    .order_by(OutboxEventRow.created_at.asc(), OutboxEventRow.event_id.asc())
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
            claimed: list[ClaimedOutboxEvent] = []
            for row in rows:
                row.claimed_by = worker_id
                row.claim_until = now + lease
                row.publish_attempt_count += 1
                try:
                    event = _event_from_row(row)
                    decode_error = None
                except (DomainError, TypeError, ValueError, AttributeError, KeyError):
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
        async with short_session(self._sessions, commit=True) as session:
            row = await self._require_claim(session, event_id=event_id, worker_id=worker_id)
            row.status = "quarantined"
            row.quarantined_at = quarantined_at
            row.last_error_code = error_code
            row.claimed_by = None
            row.claim_until = None

    async def get(self, *, event_id: UUID) -> DurableEventEnvelope | None:
        async with short_session(self._sessions) as session:
            row = await session.scalar(
                select(OutboxEventRow).where(OutboxEventRow.event_id == event_id)
            )
            return _event_from_row(row) if row is not None else None

    async def list_published_before(
        self, *, cutoff: datetime, limit: int
    ) -> tuple[DurableEventEnvelope, ...]:
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
        row = await session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.event_id == event_id).with_for_update()
        )
        if row is None:
            raise NotFoundError("outbox_event_not_found")
        if row.status != "pending" or row.claimed_by != worker_id:
            raise ConflictError("outbox_claim_lost")
        return row


class SqlAlchemyConsumptionRepository:
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
        async with short_session(self._sessions, commit=True) as session:
            row = await session.get(
                EventConsumptionRow,
                (consumer_name, consumer_version, event_id),
                with_for_update=True,
            )
            if row is None:
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
                return ConsumptionClaimResult(ConsumptionClaim.COMPLETED, row.attempt_count)
            if row.status == "dead_lettered":
                return ConsumptionClaimResult(ConsumptionClaim.DEAD_LETTERED, row.attempt_count)
            if row.lease_until is not None and row.lease_until > now:
                return ConsumptionClaimResult(ConsumptionClaim.BUSY, row.attempt_count)
            row.attempt_count += 1
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
                return ConsumptionFailureResult(
                    outcome=ConsumptionFailure.RETRY,
                    attempt=row.attempt_count,
                )
            row.status = "dead_lettered"
            row.completed_at = failed_at
            return ConsumptionFailureResult(
                outcome=ConsumptionFailure.DEAD_LETTERED,
                attempt=row.attempt_count,
            )

    async def is_terminal(
        self, *, consumer_name: str, consumer_version: int, event_id: UUID
    ) -> bool:
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
