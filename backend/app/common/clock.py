"""时钟抽象：业务时间统一从 Clock 获取。

测试注入 FrozenClock，避免断言依赖真实墙上时钟。"""

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """返回当前 UTC 时间。"""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    """测试用固定时钟，避免把时间断言绑在真实墙上时钟。"""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FrozenClock 必须使用带时区的 datetime")
        self._moment = moment

    def now(self) -> datetime:
        return self._moment
