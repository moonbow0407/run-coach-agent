"""LabClock 的推进规则与多进程同步语义。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.common.lab_clock import LabClock, LabClockError


class FakeStore:
    """内存版虚拟时钟存储：模拟 Redis key 的行为，测试不依赖真实 Redis。"""

    def __init__(self) -> None:
        self.value: datetime | None = None  # None 等价于 key 不存在

    async def get(self) -> datetime | None:
        return self.value

    async def set(self, moment: datetime) -> None:
        self.value = moment

    async def clear(self) -> None:
        self.value = None

    async def aclose(self) -> None:
        return None


async def test_now_falls_back_to_wall_clock_without_override() -> None:
    clock = LabClock(FakeStore())
    before = datetime.now(UTC)
    now = clock.now()
    after = datetime.now(UTC)
    # 无 override 时跟随墙钟：返回值必然落在真实时间区间内。
    assert before <= now <= after


async def test_start_pulls_shared_override() -> None:
    store = FakeStore()
    moment = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    store.value = moment  # 模拟另一进程（API）已经推进过时间
    clock = LabClock(store)
    await clock.start()
    try:
        # worker 进程启动即与共享值对齐，now() 不再是墙钟。
        assert clock.now() == moment
    finally:
        await clock.stop()


async def test_refresh_picks_up_external_change() -> None:
    store = FakeStore()
    clock = LabClock(store)
    await clock.start()
    try:
        assert clock.now().tzinfo is not None
        later = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
        store.value = later  # 另一进程推进共享时间
        await clock.refresh()
        assert clock.now() == later
    finally:
        await clock.stop()


async def test_set_now_moves_forward() -> None:
    clock = LabClock(FakeStore())
    moment = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    result = await clock.set_now(moment)
    assert result == moment
    assert clock.now() == moment


async def test_set_now_rejects_backwards() -> None:
    clock = LabClock(FakeStore())
    await clock.set_now(datetime(2026, 9, 12, 8, 0, tzinfo=UTC))
    with pytest.raises(LabClockError, match="lab_clock_cannot_move_backwards"):
        await clock.set_now(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))


async def test_set_now_rejects_naive_datetime() -> None:
    clock = LabClock(FakeStore())
    with pytest.raises(LabClockError, match="lab_clock_requires_timezone"):
        # 刻意传 naive datetime：验证 LabClock 拒绝无时区时间。
        await clock.set_now(datetime(2026, 9, 12, 8, 0))  # noqa: DTZ001


async def test_advance_requires_positive_delta() -> None:
    clock = LabClock(FakeStore())
    with pytest.raises(LabClockError, match="lab_clock_advance_requires_positive_delta"):
        await clock.advance()


async def test_advance_moves_from_current_virtual_now() -> None:
    clock = LabClock(FakeStore())
    base = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    await clock.set_now(base)
    await clock.advance(days=7, hours=2)
    assert clock.now() == base + timedelta(days=7, hours=2)


async def test_reset_to_wall_clears_store_and_override() -> None:
    store = FakeStore()
    clock = LabClock(store)
    await clock.set_now(datetime(2026, 9, 12, 8, 0, tzinfo=UTC))
    before = datetime.now(UTC)
    await clock.reset_to_wall()
    now = clock.now()
    after = datetime.now(UTC)
    # 重置后回到墙钟：override 清空、共享 key 删除。
    assert store.value is None
    assert before <= now <= after
