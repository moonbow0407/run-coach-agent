"""真实 Redis / ARQ delivery 与 PostgreSQL receipt 去重。"""

from datetime import timedelta

import pytest
from arq.connections import RedisSettings, create_pool
from arq.worker import Worker

from app.agent.contracts.durable_events import (
    TURN_FAILED_V1,
    TurnTerminalV1,
    new_turn_terminal_event,
)
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.outbox.writer import OutboxWriter
from app.infrastructure.queue.arq_adapter import ArqQueuePublisher
from app.workers.arq_worker import consume_durable_task
from app.workers.consumer import ConsumerRunner, TaskOutcome
from app.workers.errors import PermanentWorkerError, TransientWorkerError
from app.workers.publisher import OutboxPublisher
from app.workers.recovery import OutboxRecoveryScanner
from app.workers.routing import FINALIZE_TERMINAL_TURN

REDIS_DB = 14
QUEUE_NAME = "arq:phase5-integration"


@pytest.mark.asyncio
async def test_arq_duplicate_delivery_has_one_completed_receipt(
    sessions,
    user_id,
    clock,
) -> None:
    """验证：同一事件被 ARQ 重复投递（崩溃恢复重投 + 手动重发），handler 只执行一次，receipt 幂等去重。"""
    # 直连本机真实 Redis（DB 14），测试前后 flushdb 清库，finally 保证清理。
    redis = await create_pool(RedisSettings(host="localhost", port=6379, database=REDIS_DB))
    await redis.flushdb()
    try:
        turn_id = new_id()
        event = new_turn_terminal_event(
            event_type=TURN_FAILED_V1,
            user_id=user_id,
            payload=TurnTerminalV1(
                turn_id=turn_id,
                thread_id=new_id(),
                run_id=new_id(),
                terminal_at=clock.now(),
            ),
            metadata=EventMetadata(correlation_id=new_id()),
        )
        async with sessions.begin() as session:
            OutboxWriter().add(session, event)

        calls = 0

        async def handler(task) -> TaskOutcome:
            nonlocal calls
            calls += 1
            return TaskOutcome.SUCCESS

        receipts = SqlAlchemyConsumptionRepository(sessions)
        runner = ConsumerRunner(
            receipts=receipts,
            handlers={FINALIZE_TERMINAL_TURN: handler},
            clock=clock,
            worker_id="arq-integration-consumer",
        )
        queue = ArqQueuePublisher(redis, queue_name=QUEUE_NAME)
        publisher = OutboxPublisher(
            repository=SqlAlchemyOutboxRepository(sessions),
            queue=queue,
            clock=clock,
            worker_id="arq-integration-publisher",
        )
        published = await publisher.publish_batch()
        assert published.published == 1

        # 模拟 publisher enqueue 成功后崩溃：恢复扫描重复 enqueue 原 deterministic job id。
        recovery = OutboxRecoveryScanner(
            outbox=SqlAlchemyOutboxRepository(sessions),
            queue=queue,
            clock=clock,
            safety_window=timedelta(0),
        )
        before_consume = await recovery.scan()
        assert before_consume.tasks_reenqueued == 1

        await _run_burst(redis, runner)
        assert calls == 1

        task = (await _published_task(event, clock))[0]
        await queue.enqueue(task)
        await _run_burst(redis, runner)
        assert calls == 1
        assert await receipts.is_terminal(
            consumer_name=FINALIZE_TERMINAL_TURN,
            consumer_version=1,
            event_id=event.event_id,
        )

        result = await recovery.scan()
        assert result.tasks_reenqueued == 0
        assert result.events_scanned == 0
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.mark.asyncio
async def test_arq_transient_retry_succeeds_and_permanent_failure_dead_letters(
    sessions,
    user_id,
    clock,
) -> None:
    """验证：瞬时错误自动重试后成功完成，永久错误直接死信；两类错误的 receipt 都到达终态。"""
    redis = await create_pool(RedisSettings(host="localhost", port=6379, database=REDIS_DB))
    await redis.flushdb()
    try:
        transient_event = new_turn_terminal_event(
            event_type=TURN_FAILED_V1,
            user_id=user_id,
            payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
            metadata=EventMetadata(correlation_id=new_id()),
        )
        permanent_event = new_turn_terminal_event(
            event_type=TURN_FAILED_V1,
            user_id=user_id,
            payload=TurnTerminalV1(new_id(), new_id(), new_id(), clock.now()),
            metadata=EventMetadata(correlation_id=new_id()),
        )
        async with sessions.begin() as session:
            OutboxWriter().add(session, transient_event)

        attempts = 0
        logical_results = set()

        async def handler(task) -> TaskOutcome:
            nonlocal attempts
            if task.event.event_id == permanent_event.event_id:
                raise PermanentWorkerError("cross_user_source")
            attempts += 1
            # 模拟 service 已提交而 receipt 尚未 complete 就崩溃；重试只命中同一逻辑结果。
            logical_results.add(task.event.event_id)
            if attempts == 1:
                raise TransientWorkerError("embedding_temporarily_unavailable")
            return TaskOutcome.SUCCESS

        receipts = SqlAlchemyConsumptionRepository(sessions)
        runner = ConsumerRunner(
            receipts=receipts,
            handlers={FINALIZE_TERMINAL_TURN: handler},
            clock=clock,
            worker_id="arq-retry-consumer",
        )
        publisher = OutboxPublisher(
            repository=SqlAlchemyOutboxRepository(sessions),
            queue=ArqQueuePublisher(redis, queue_name=QUEUE_NAME),
            clock=clock,
            worker_id="arq-retry-publisher",
        )
        await publisher.publish_batch()
        # ARQ burst worker 会等待首个 delayed retry 到期，因此一次运行即可观察完整重试链。
        await _run_burst(redis, runner)
        assert attempts == 2
        assert logical_results == {transient_event.event_id}
        assert await receipts.is_terminal(
            consumer_name=FINALIZE_TERMINAL_TURN,
            consumer_version=1,
            event_id=transient_event.event_id,
        )

        async with sessions.begin() as session:
            OutboxWriter().add(session, permanent_event)
        await publisher.publish_batch()
        await _run_burst(redis, runner)
        assert await receipts.is_terminal(
            consumer_name=FINALIZE_TERMINAL_TURN,
            consumer_version=1,
            event_id=permanent_event.event_id,
        )
    finally:
        await redis.flushdb()
        await redis.aclose()

async def _run_burst(redis, runner: ConsumerRunner) -> None:
    """用真实 arq Worker 以 burst 模式消费：跑完当前队列即退出，任务经 ctx 注入 ConsumerRunner。"""
    worker = Worker(
        functions=[consume_durable_task],
        redis_pool=redis,
        queue_name=QUEUE_NAME,
        burst=True,
        ctx={"consumer_runner": runner},
        keep_result=0,
        max_tries=8,
        handle_signals=False,
    )
    await worker.async_run()


async def _published_task(event, clock):
    """按正式路由规则把事件包装成队列任务（含确定性 job id）。"""
    from app.workers.routing import route_event

    return route_event(event, enqueued_at=clock.now())
