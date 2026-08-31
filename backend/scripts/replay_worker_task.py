"""按 event_id + consumer_name + consumer_version 显式重放一个 dead-letter task。"""

import argparse
import asyncio
import json
from dataclasses import asdict
from uuid import UUID

from arq.connections import RedisSettings, create_pool

from app.common.clock import SystemClock
from app.infrastructure.config import Settings
from app.infrastructure.database.session import create_engine, create_session_factory
from app.infrastructure.outbox.repository import (
    SqlAlchemyConsumptionRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.queue.arq_adapter import ArqQueuePublisher
from app.workers.replay import WorkerTaskReplayer


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", required=True, type=UUID)
    parser.add_argument("--consumer-name", required=True)
    parser.add_argument("--consumer-version", required=True, type=int)
    return parser.parse_args()


async def main() -> None:
    args = _arguments()
    settings = Settings()
    engine = create_engine(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        sessions = create_session_factory(engine)
        result = await WorkerTaskReplayer(
            outbox=SqlAlchemyOutboxRepository(sessions),
            receipts=SqlAlchemyConsumptionRepository(sessions),
            queue=ArqQueuePublisher(redis, queue_name=settings.worker_queue_name),
            clock=SystemClock(),
        ).replay(
            event_id=args.event_id,
            consumer_name=args.consumer_name,
            consumer_version=args.consumer_version,
        )
        print(json.dumps(asdict(result), default=str, ensure_ascii=False))
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
