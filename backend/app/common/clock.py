"""时钟抽象：业务时间统一从 Clock 获取。

测试注入 FrozenClock，避免断言依赖真实墙上时钟。"""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """时钟抽象：业务代码只依赖本接口取时间，不直接调 datetime.now。"""

    # Protocol：结构化鸭子类型，只约束方法签名，实现类无需显式继承。
    def now(self) -> datetime:
        """返回当前 UTC 时间。"""
        ...


class SystemClock:
    """生产环境默认时钟，返回真实的当前 UTC 时间。"""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """测试用固定时钟，避免把时间断言绑在真实墙上时钟。"""

    def __init__(self, moment: datetime) -> None:
        # 无时区的时间无法与 UTC 事件流对齐比较，直接拒绝而非静默假定。
        if moment.tzinfo is None:
            raise ValueError("FrozenClock 必须使用带时区的 datetime")
        self._moment = moment  # 冻结的"当前时刻"，每次 now() 都返回它

    def now(self) -> datetime:
        return self._moment
