"""Consumer receipt、分类与 Application Service handler 调度。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

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
        try:
            validate_task_route(task)
        except DomainError as exc:
            raise PermanentWorkerError("invalid_worker_task_schema") from exc
        handler = self._handlers.get(task.task_name)
        if handler is None:
            raise PermanentWorkerError("worker_task_handler_missing")
        claim = await self._receipts.claim(
            consumer_name=task.task_name,
            consumer_version=task.task_version,
            event_id=task.event.event_id,
            user_id=task.event.user_id,
            worker_id=self._worker_id,
            now=self._clock.now(),
            lease=self._lease,
        )
        if claim is ConsumptionClaim.COMPLETED:
            return ConsumeResult("already_completed")
        if claim is ConsumptionClaim.DEAD_LETTERED:
            return ConsumeResult("already_dead_lettered")
        if claim is ConsumptionClaim.BUSY:
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
                raise WorkerRetryRequested(
                    code,
                    defer_seconds=max(1, int(delay.total_seconds())),
                ) from exc
            return ConsumeResult("dead_lettered", attempt=failure.attempt)

        await self._receipts.complete(
            consumer_name=task.task_name,
            consumer_version=task.task_version,
            event_id=task.event.event_id,
            worker_id=self._worker_id,
            completed_at=self._clock.now(),
        )
        return ConsumeResult(outcome.value)


_PERMANENT_INFRASTRUCTURE_CODES = {
    "memory_embedding_provider_not_configured",
    "memory_extractor_not_configured",
    "memory_embedding_contract_mismatch",
    "memory_embedding_dimension_mismatch",
}


def _classify(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, TransientWorkerError):
        return exc.code, True
    if isinstance(exc, PermanentWorkerError):
        return exc.code, False
    if isinstance(exc, NotFoundError):
        return "canonical_source_not_found", False
    if isinstance(exc, DomainError):
        return exc.code, False
    if isinstance(exc, InfrastructureError):
        code = getattr(exc, "code", str(exc))
        return str(code), str(code) not in _PERMANENT_INFRASTRUCTURE_CODES
    return "worker_internal_error", False
