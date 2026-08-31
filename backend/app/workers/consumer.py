"""Consumer receipt、分类、结构化日志与 Application Service handler 调度。"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from time import perf_counter

from sqlalchemy.exc import DataError, DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.exc import TimeoutError as SqlAlchemyTimeoutError

from app.common.clock import Clock
from app.common.errors import DomainError, InfrastructureError, NotFoundError
from app.infrastructure.outbox.repository import (
    ConsumptionClaim,
    ConsumptionFailure,
    SqlAlchemyConsumptionRepository,
)
from app.workers.contracts import WorkerTaskEnvelope
from app.workers.errors import PermanentWorkerError, TransientWorkerError, WorkerRetryRequested
from app.workers.retry import MAX_ATTEMPTS, retry_delay
from app.workers.routing import validate_task_route

logger = logging.getLogger(__name__)


class TaskOutcome(StrEnum):
    SUCCESS = "success"
    OBSOLETE_NOOP = "obsolete_noop"


TaskHandler = Callable[[WorkerTaskEnvelope], Awaitable[TaskOutcome]]


@dataclass(frozen=True)
class ConsumeResult:
    status: str
    attempt: int | None = None


class ConsumerRunner:
    def __init__(
        self,
        *,
        receipts: SqlAlchemyConsumptionRepository,
        handlers: dict[str, TaskHandler],
        clock: Clock,
        worker_id: str,
        lease: timedelta = timedelta(minutes=10),
    ) -> None:
        self._receipts = receipts
        self._handlers = handlers
        self._clock = clock
        self._worker_id = worker_id
        self._lease = lease

    async def consume(self, task: WorkerTaskEnvelope) -> ConsumeResult:
        started = perf_counter()
        try:
            validate_task_route(task)
        except DomainError as exc:
            raise PermanentWorkerError("invalid_worker_task_schema") from exc
        handler = self._handlers.get(task.task_name)
        if handler is None:
            raise PermanentWorkerError("worker_task_handler_missing")
        try:
            claim = await self._receipts.claim(
                consumer_name=task.task_name,
                consumer_version=task.task_version,
                event_id=task.event.event_id,
                user_id=task.event.user_id,
                worker_id=self._worker_id,
                now=self._clock.now(),
                lease=self._lease,
            )
        except (DBAPIError, SqlAlchemyTimeoutError) as exc:
            raise WorkerRetryRequested(
                "database_temporarily_unavailable", defer_seconds=5
            ) from exc
        if claim.outcome is ConsumptionClaim.COMPLETED:
            self._log(task, "already_completed", claim.attempt, started=started)
            return ConsumeResult("already_completed", attempt=claim.attempt)
        if claim.outcome is ConsumptionClaim.DEAD_LETTERED:
            self._log(task, "already_dead_lettered", claim.attempt, started=started)
            return ConsumeResult("already_dead_lettered", attempt=claim.attempt)
        if claim.outcome is ConsumptionClaim.BUSY:
            self._log(
                task,
                "lease_busy",
                claim.attempt,
                error_code="consumer_lease_busy",
                started=started,
            )
            raise WorkerRetryRequested("consumer_lease_busy", defer_seconds=5)

        try:
            outcome = await handler(task)
            if outcome not in {TaskOutcome.SUCCESS, TaskOutcome.OBSOLETE_NOOP}:
                raise PermanentWorkerError("invalid_task_outcome")
        except Exception as exc:
            code, transient = _classify(exc)
            failure = await self._receipts.fail(
                consumer_name=task.task_name,
                consumer_version=task.task_version,
                event_id=task.event.event_id,
                worker_id=self._worker_id,
                failed_at=self._clock.now(),
                error_code=code,
                retryable=transient,
                max_attempts=MAX_ATTEMPTS,
            )
            if failure.outcome is ConsumptionFailure.RETRY:
                delay = retry_delay(
                    attempt=failure.attempt,
                    event_id=task.event.event_id,
                )
                self._log(
                    task,
                    "retrying",
                    failure.attempt,
                    error_code=code,
                    started=started,
                )
                raise WorkerRetryRequested(
                    code,
                    defer_seconds=max(1, int(delay.total_seconds())),
                ) from exc
            self._log(
                task,
                "dead_lettered",
                failure.attempt,
                error_code=code,
                started=started,
            )
            return ConsumeResult("dead_lettered", attempt=failure.attempt)

        try:
            await self._receipts.complete(
                consumer_name=task.task_name,
                consumer_version=task.task_version,
                event_id=task.event.event_id,
                worker_id=self._worker_id,
                completed_at=self._clock.now(),
            )
        except (DBAPIError, SqlAlchemyTimeoutError) as exc:
            # 业务 service 可能已经提交；下次 delivery 依靠 service 幂等与 receipt 接管完成。
            raise WorkerRetryRequested(
                "database_temporarily_unavailable", defer_seconds=5
            ) from exc
        self._log(task, outcome.value, claim.attempt, started=started)
        return ConsumeResult(outcome.value, attempt=claim.attempt)

    def _log(
        self,
        task: WorkerTaskEnvelope,
        status: str,
        attempt: int,
        *,
        started: float,
        error_code: str | None = None,
    ) -> None:
        event = task.event
        logger.info(
            "worker.task.consumed",
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "schema_version": event.schema_version,
                "task_name": task.task_name,
                "task_version": task.task_version,
                "consumer_name": task.task_name,
                "user_id": str(event.user_id),
                "correlation_id": str(event.metadata.correlation_id),
                "trace_id": (
                    str(event.metadata.trace_id)
                    if event.metadata.trace_id is not None
                    else None
                ),
                "attempt": attempt,
                "worker_id": self._worker_id,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "status": status,
                "error_code": error_code,
            },
        )


_PERMANENT_INFRASTRUCTURE_CODES = {
    "memory_embedding_provider_not_configured",
    "memory_extractor_not_configured",
    "memory_embedding_contract_mismatch",
    "memory_embedding_dimension_mismatch",
}

_PERMANENT_DATABASE_ERRORS = (IntegrityError, DataError, ProgrammingError)


def _classify(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, TransientWorkerError):
        return exc.code, True
    if isinstance(exc, PermanentWorkerError):
        return exc.code, False
    if isinstance(exc, NotFoundError):
        return "canonical_source_not_found", False
    if isinstance(exc, DomainError):
        return exc.code, False
    if isinstance(exc, _PERMANENT_DATABASE_ERRORS):
        return "database_constraint_error", False
    if isinstance(exc, (DBAPIError, SqlAlchemyTimeoutError)):
        return "database_temporarily_unavailable", True
    if isinstance(exc, InfrastructureError):
        code = getattr(exc, "code", str(exc))
        return str(code), str(code) not in _PERMANENT_INFRASTRUCTURE_CODES
    return "worker_internal_error", False