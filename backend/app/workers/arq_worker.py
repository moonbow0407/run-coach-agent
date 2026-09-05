"""ARQ worker process bootstrap、publisher cron 与 durable consumer 入口。"""

import logging
import socket
from datetime import timedelta
from typing import ClassVar

from arq import Retry, cron
from arq.connections import RedisSettings

from app.bootstrap import AppContainer, build_container
from app.common.lab_clock import LabClock
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
    """Worker 启动钩子：装配消费、发布、恢复三条链路的依赖并挂到 ctx 共享。"""
    settings = Settings()
    container = build_container(settings)
    # Worker 实例标识（主机名 + 进程内对象 id），写入回执便于排查是谁消费的。
    worker_id = f"{socket.gethostname()}:{id(ctx)}"
    # 消费回执仓库：实现幂等去重与死信判定。
    receipts = SqlAlchemyConsumptionRepository(container.sessions)
    # outbox（本地消息表）仓库：待发布事件的读取入口。
    outbox = SqlAlchemyOutboxRepository(container.sessions)
    # 队列发布端口，复用 arq 注入的 Redis 连接。
    queue = ArqQueuePublisher(ctx["redis"], queue_name=settings.worker_queue_name)
    # 四类 durable task 的正式业务处理器。
    handlers = DurableTaskHandlers(
        terminal_turn_finalization=container.terminal_turn_finalization_service,
        athlete_recompute=container.athlete_recompute_service,
        semantic_projection=container.semantic_memory_projection_service,
        episode_projection=container.episode_projection_service,
        memory_projector_version=settings.memory_projector_version,
    )
    ctx["app_container"] = container  # 供 shutdown 钩子释放资源
    # lab 开启时 worker 与 API 共享 Redis 虚拟时钟：启动即拉取，Redis 不可达直接失败。
    if isinstance(container.clock, LabClock):
        await container.clock.start()
    # 幂等消费者：真正执行任务并管理重试 / 死信。
    ctx["consumer_runner"] = ConsumerRunner(
        receipts=receipts,
        handlers=handlers.mapping(),
        clock=container.clock,
        worker_id=worker_id,
    )
    # outbox 发布器：把业务事件投递到队列。
    ctx["outbox_publisher"] = OutboxPublisher(
        repository=outbox,
        queue=queue,
        clock=container.clock,
        worker_id=worker_id,
    )
    # 恢复扫描器：兜底重建 Redis 中丢失的任务。
    ctx["recovery_scanner"] = OutboxRecoveryScanner(
        outbox=outbox,
        queue=queue,
        clock=container.clock,
    )


async def shutdown(ctx: dict) -> None:
    """Worker 退出钩子：停止 lab 时钟、释放数据库连接池等进程级资源。"""
    container: AppContainer | None = ctx.get("app_container")
    if container is not None:
        if isinstance(container.clock, LabClock):
            await container.clock.stop()
        await container.engine.dispose()


async def consume_durable_task(ctx: dict, raw_task: dict[str, object]) -> None:
    """arq 任务入口：还原任务信封并交给幂等消费者执行。"""
    # 队列里是 JSON 字典，先还原成强类型任务信封（格式非法直接报错）。
    task = WorkerTaskEnvelope.from_dict(raw_task)
    runner: ConsumerRunner = ctx["consumer_runner"]
    try:
        result = await runner.consume(task)
    except WorkerRetryRequested as exc:
        # 消费者要求延迟重试：转成 arq 的 Retry（不算成功 ack，稍后重新投递）。
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
    """cron 入口：轮询 outbox（本地消息表）并投递新事件到队列。"""
    publisher: OutboxPublisher = ctx["outbox_publisher"]
    await publisher.publish_batch()


async def recover_missing_tasks(ctx: dict) -> None:
    """cron 入口：扫描并重建在 Redis 中丢失的任务（兜底恢复）。"""
    scanner: OutboxRecoveryScanner = ctx["recovery_scanner"]
    await scanner.scan()


_worker_settings = Settings()


class WorkerSettings:
    """arq Worker 配置：arq 直接读取类属性作为设置。

    ClassVar 表示类级常量（不随实例变化），arq 据此识别可配置项。
    """

    functions: ClassVar[list] = [consume_durable_task]  # 注册的普通任务：消费 durable task
    on_startup = startup  # 启动钩子：装配依赖
    on_shutdown = shutdown  # 退出钩子：释放资源
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
    # Redis 连接与队列名来自统一配置。
    redis_settings = RedisSettings.from_dsn(_worker_settings.redis_url)
    queue_name = _worker_settings.worker_queue_name
    max_tries = 8  # 单个任务最多尝试 8 次（含首次），与消费侧退避计划对齐
    job_timeout = timedelta(minutes=10)  # 单个任务最长执行 10 分钟，超时按失败处理
    keep_result = 0  # 不保留任务返回值（结果由消费回执与日志承载）
    health_check_interval = 30  # arq 健康检查间隔（秒）
