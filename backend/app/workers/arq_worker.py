"""ARQ worker process bootstrap、publisher cron 与 durable consumer 入口。"""

import logging
import socket
from datetime import timedelta
from typing import ClassVar

from arq import Retry, cron
from arq.connections import RedisSettings

from app.bootstrap import AppContainer, build_container
from app.infrastructure.config import Settings
from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.queue.arq_adapter import ArqQueuePublisher
from app.workers.consumer import ConsumerRunner
from app.workers.contracts import WorkerTaskEnvelope
from app.workers.errors import WorkerRetryRequested
from app.workers.handlers import DurableTaskHandlers
from app.workers.publisher import OutboxPublisher
from app.workers.recovery import OutboxRecoveryScanner

logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    settings = Settings()
    container = build_container(settings)
    worker_id = f"{socket.gethostname()}:{id(ctx)}"
    receipts = SqlAlchemyConsumptionRepository(container.sessions)
    outbox = SqlAlchemyOutboxRepository(container.sessions)
    queue = ArqQueuePublisher(ctx["redis"], queue_name=settings.worker_queue_name)
    handlers = DurableTaskHandlers(
        terminal_turn_finalization=container.terminal_turn_finalization_service,
        athlete_recompute=container.athlete_recompute_service,
        semantic_projection=container.semantic_memory_projection_service,
        episode_projection=container.episode_projection_service,
        memory_projector_version=settings.memory_projector_version,
    )
    ctx["app_container"] = container
    ctx["consumer_runner"] = ConsumerRunner(
        receipts=receipts,
        handlers=handlers.mapping(),
        clock=container.clock,
        worker_id=worker_id,
    )
    ctx["outbox_publisher"] = OutboxPublisher(
        repository=outbox,
        queue=queue,
        clock=container.clock,
        worker_id=worker_id,
    )
    ctx["recovery_scanner"] = OutboxRecoveryScanner(
        outbox=outbox,
        queue=queue,
        clock=container.clock,
    )


async def shutdown(ctx: dict) -> None:
    container: AppContainer | None = ctx.get("app_container")
    if container is not None:
        await container.engine.dispose()


async def consume_durable_task(ctx: dict, raw_task: dict[str, object]) -> None:
    task = WorkerTaskEnvelope.from_dict(raw_task)
    runner: ConsumerRunner = ctx["consumer_runner"]
    try:
        result = await runner.consume(task)
    except WorkerRetryRequested as exc:
        raise Retry(defer=exc.defer_seconds) from exc
    logger.info(
        "worker.task.finished",
        extra={
            "event_id": str(task.event.event_id),
            "event_type": task.event.event_type,
            "task_name": task.task_name,
            "task_version": task.task_version,
            "user_id": str(task.event.user_id),
            "correlation_id": str(task.event.metadata.correlation_id),
            "trace_id": (
                str(task.event.metadata.trace_id)
                if task.event.metadata.trace_id is not None
                else None
            ),
            "attempt": result.attempt,
            "status": result.status,
        },
    )


async def publish_outbox(ctx: dict) -> None:
    publisher: OutboxPublisher = ctx["outbox_publisher"]
    await publisher.publish_batch()


async def recover_missing_tasks(ctx: dict) -> None:
    scanner: OutboxRecoveryScanner = ctx["recovery_scanner"]
    await scanner.scan()


_worker_settings = Settings()


class WorkerSettings:
    functions: ClassVar[list] = [consume_durable_task]
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs: ClassVar[list] = [
        cron(
            publish_outbox,
            second={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=True,
            unique=True,
            max_tries=1,
        ),
        cron(
            recover_missing_tasks,
            minute={0, 10, 20, 30, 40, 50},
            second=30,
            run_at_startup=False,
            unique=True,
            max_tries=1,
        ),
    ]
    redis_settings = RedisSettings.from_dsn(_worker_settings.redis_url)
    queue_name = _worker_settings.worker_queue_name
    max_tries = 8
    job_timeout = timedelta(minutes=10)
    keep_result = 0
    health_check_interval = 30
