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
    """handler 的处理结论（StrEnum：成员可直接当字符串使用）。"""

    SUCCESS = "success"
    OBSOLETE_NOOP = "obsolete_noop"  # 事件已过时（被后续事件覆盖），幂等跳过、视为处理完成


# 任务名 → 处理器的类型别名：每个处理器接收任务信封，异步返回处理结论。
TaskHandler = Callable[[WorkerTaskEnvelope], Awaitable[TaskOutcome]]


@dataclass(frozen=True)
class ConsumeResult:
    """一次消费的结果摘要（不可变数据类），供日志与调用方使用。"""

    status: str  # 终态：success / obsolete_noop / already_completed / dead_lettered 等
    attempt: int | None = None  # 消费回执记录的累计尝试次数（可能为空）


class ConsumerRunner:
    """durable task 的幂等消费者：抢占消费回执（lease 租约）→ 执行 handler → 按结果记录成功 / 重试 / 死信。"""

    def __init__(
        self,
        *,
        receipts: SqlAlchemyConsumptionRepository,
        handlers: dict[str, TaskHandler],
        clock: Clock,
        worker_id: str,
        lease: timedelta = timedelta(minutes=10),
    ) -> None:
        self._receipts = receipts  # 消费回执仓库：claim/complete/fail，负责幂等去重与死信判定
        self._handlers = handlers  # 任务名 → 处理器注册表
        self._clock = clock  # 时钟：统一取“当前时间”，便于测试注入
        self._worker_id = worker_id  # 本 Worker 标识，写入回执便于追踪
        self._lease = lease  # 租约时长：超时未完成视为 Worker 崩溃，回执可被重新抢占

    async def consume(self, task: WorkerTaskEnvelope) -> ConsumeResult:
        """执行一次投递：抢占回执 → 调用 handler → 记录成功 / 重试 / 死信。"""
        # 记录起始时间，用于统计本次消费耗时。
        started = perf_counter()
        try:
            validate_task_route(task)
        except DomainError as exc:
            # 路由校验失败属永久错误：信封与路由表不符，重试无意义。
            raise PermanentWorkerError("invalid_worker_task_schema") from exc
        # 未知任务名说明路由表与代码不同步，属永久错误。
        handler = self._handlers.get(task.task_name)
        if handler is None:
            raise PermanentWorkerError("worker_task_handler_missing")
        try:
            # 抢占消费回执：同一事件 + 同一任务只允许一个 Worker 在租约内消费（幂等去重）。
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
            # 数据库暂时不可用：稍后整条重试，不算业务失败。
            raise WorkerRetryRequested(
                "database_temporarily_unavailable", defer_seconds=5
            ) from exc
        if claim.outcome is ConsumptionClaim.COMPLETED:
            # 之前已成功消费过（回执去重）：直接当成功返回，不重复执行。
            self._log(task, "already_completed", claim.attempt, started=started)
            return ConsumeResult("already_completed", attempt=claim.attempt)
        if claim.outcome is ConsumptionClaim.DEAD_LETTERED:
            # 该任务已被判死信（重试耗尽），不再执行，等待人工 replay。
            self._log(task, "already_dead_lettered", claim.attempt, started=started)
            return ConsumeResult("already_dead_lettered", attempt=claim.attempt)
        if claim.outcome is ConsumptionClaim.BUSY:
            # 其他 Worker 正持有租约：延迟重投，避免并发重复消费。
            self._log(
                task,
                "lease_busy",
                claim.attempt,
                error_code="consumer_lease_busy",
                started=started,
            )
            raise WorkerRetryRequested("consumer_lease_busy", defer_seconds=5)

        try:
            # 执行业务 handler；任何异常都先归类（临时 / 永久），再决定重试或死信。
            outcome = await handler(task)
            if outcome not in {TaskOutcome.SUCCESS, TaskOutcome.OBSOLETE_NOOP}:
                # handler 返回未知结论视为契约破坏，按永久错误处理。
                raise PermanentWorkerError("invalid_task_outcome")
        except Exception as exc:
            code, transient = _classify(exc)
            # 把失败写入回执：由回执统一判定是继续重试还是判死信。
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
                # 未达最大尝试次数：按退避计划延迟重投。
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
            # 重试耗尽：写死信（dead letter），等待人工 replay。
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
        """输出结构化消费日志：链路追踪 ID、尝试次数、耗时与终态，便于排障与审计。"""
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


# 这些基础设施错误源于配置 / 契约缺失，重试不会好转，按永久失败处理。
_PERMANENT_INFRASTRUCTURE_CODES = {
    "memory_embedding_provider_not_configured",
    "memory_extractor_not_configured",
    "memory_embedding_contract_mismatch",
    "memory_embedding_dimension_mismatch",
}

# 约束冲突 / 数据格式类数据库错误：重试无意义，按永久失败处理。
_PERMANENT_DATABASE_ERRORS = (IntegrityError, DataError, ProgrammingError)


def _classify(exc: Exception) -> tuple[str, bool]:
    """把任意异常归一化为（错误码, 是否可重试）；未识别异常按内部错误处理且不重试。"""
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
        # 基础设施错误：已知永久码之外默认可重试（如外部服务抖动）。
        code = getattr(exc, "code", str(exc))
        return str(code), str(code) not in _PERMANENT_INFRASTRUCTURE_CODES
    return "worker_internal_error", False