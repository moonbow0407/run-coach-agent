"""可推进的演示时钟（Scenario Lab）：lab 模式下 API 与 worker 共享同一个"业务现在"。

设计约束：Clock 协议的 now() 是同步方法，而共享存储（Redis）读取是异步 IO，
因此采用「进程内 override + 后台协程周期同步」：
  - now() 热路径零 IO，直接返回进程内 override（缺失则回退墙钟）；
  - refresh() 周期从共享存储拉取最新虚拟时刻，另一进程的推进最迟一个周期可见。
与 EvalClock 一致只允许前进：事件 available_at / 快照 as_of 的单调性依赖它。
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)

# 多进程同步周期：worker 最迟此时长后看到 API 推进的时间（arq cron 本身 5s，量级匹配）。
REFRESH_INTERVAL_S = 1.0


class LabClockError(Exception):
    """Lab 时钟违规操作：时间倒流、未带时区、无增量等，由调用方归一化为 4xx。"""


class VirtualClockStore(Protocol):
    """虚拟时钟共享存储端口：key 缺失的语义即「lab 未设定，跟随墙钟」。"""

    async def get(self) -> datetime | None: ...
    async def set(self, moment: datetime) -> None: ...
    async def clear(self) -> None: ...
    async def aclose(self) -> None: ...


class LabClock:
    """可推进的业务时钟：进程内 override + 与共享存储周期同步。"""

    def __init__(self, store: VirtualClockStore) -> None:
        self._store = store
        self._override: datetime | None = None  # 进程内虚拟"现在"；None 表示跟随墙钟
        self._loop_task: asyncio.Task[None] | None = None

    def now(self) -> datetime:
        """业务当前时刻：lab override 优先，否则真实墙钟（UTC）。"""
        return self._override or datetime.now(UTC)

    async def start(self) -> None:
        """启动时钟：先同步拉取一次共享值（Redis 不可达立即失败），再起后台循环。"""
        self._override = await self._store.get()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        """停止后台循环并释放存储连接；进程退出时调用。"""
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass  # 任务被取消是 stop 的预期路径
            self._loop_task = None
        await self._store.aclose()

    async def refresh(self) -> None:
        """从共享存储拉取最新虚拟时刻；另一进程 set/advance 后经此生效。"""
        self._override = await self._store.get()

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001  # 长驻循环的运行期边界，见下
                # 长驻同步循环的运行期边界：扛过 Redis 瞬断，期间保持上次值并留痕。
                logger.warning("lab_clock_refresh_failed: %s", exc)
            await asyncio.sleep(REFRESH_INTERVAL_S)

    async def set_now(self, moment: datetime) -> datetime:
        """把业务时间设定到指定时刻；只允许前进（快照/事件的单调性依赖）。"""
        if moment.tzinfo is None:
            raise LabClockError("lab_clock_requires_timezone")
        current = self.now()
        if moment < current:
            raise LabClockError("lab_clock_cannot_move_backwards")
        await self._store.set(moment)
        self._override = moment
        return moment

    async def advance(self, *, days: int = 0, hours: int = 0) -> datetime:
        """从当前虚拟时刻向前推进；零增量视为调用错误而非静默无操作。"""
        if days <= 0 and hours <= 0:
            raise LabClockError("lab_clock_advance_requires_positive_delta")
        return await self.set_now(self.now() + timedelta(days=days, hours=hours))

    async def reset_to_wall(self) -> datetime:
        """清除虚拟时刻，回到真实墙上时钟（lab 场景重置的兜底动作）。"""
        await self._store.clear()
        self._override = None
        return datetime.now(UTC)
