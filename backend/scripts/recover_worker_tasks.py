"""手工扫描 PostgreSQL 已发布事件并重建缺失的 ARQ tasks。"""

import asyncio
import json
from dataclasses import asdict

from arq.connections import RedisSettings, create_pool

from app.common.clock import SystemClock
from app.infrastructure.config import Settings
from app.infrastructure.database.session import create_engine, create_session_factory
from app.infrastructure.outbox.repository import (
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.queue.arq_adapter import ArqQueuePublisher
from app.workers.recovery import OutboxRecoveryScanner


async def main() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        sessions = create_session_factory(engine)
        result = await OutboxRecoveryScanner(
            outbox=SqlAlchemyOutboxRepository(sessions),
            queue=ArqQueuePublisher(redis, queue_name=settings.worker_queue_name),
            clock=SystemClock(),
        ).scan()
        print(json.dumps(asdict(result), ensure_ascii=False))
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
