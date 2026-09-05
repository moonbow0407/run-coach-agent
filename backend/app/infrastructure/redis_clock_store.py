"""LabClock 虚拟时刻的 Redis 存储实现：单 key 存 ISO UTC 时刻，无 TTL。

Redis 在本仓库只承载 lab 演示状态与任务队列，不是业务事实；
key 丢失（如 Redis 重启）的语义就是「未设定 → 回退墙钟」，重新 advance 即可。
连接懒建立：build_container 是同步函数，无法在装配期完成异步连接。
"""

from datetime import datetime

from arq.connections import ArqRedis, RedisSettings, create_pool

from app.common.lab_clock import LabClockError

_LAB_CLOCK_KEY = "run_coach:lab:clock"


class RedisVirtualClockStore:
    """以一个 Redis key 承载 lab 虚拟"现在"，供 API 与 worker 两进程对齐。"""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: ArqRedis | None = None  # 懒建立的 Redis 连接池

    async def _ensure_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        return self._pool

    async def get(self) -> datetime | None:
        pool = await self._ensure_pool()
        raw = await pool.get(_LAB_CLOCK_KEY)
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else raw
        moment = datetime.fromisoformat(text)
        # 存储内容只允许带时区的 ISO 串；出现 naive 值说明写入方违约，直接暴露。
        if moment.tzinfo is None:
            raise LabClockError("lab_clock_store_requires_timezone")
        return moment

    async def set(self, moment: datetime) -> None:
        pool = await self._ensure_pool()
        await pool.set(_LAB_CLOCK_KEY, moment.isoformat())

    async def clear(self) -> None:
        pool = await self._ensure_pool()
        await pool.delete(_LAB_CLOCK_KEY)

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
