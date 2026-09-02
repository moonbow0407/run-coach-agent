"""跑者状态快照的跨模块只读仓储端口。"""

from typing import Protocol  # Protocol：结构化鸭子类型，只约束方法签名，不要求继承
from uuid import UUID

from app.coaching.domain.athlete.models import AthleteStateSnapshot


class AthleteStateRepository(Protocol):
    """Athlete State 的跨模块只读端口；写入只允许经 Recompute UoW。"""

    # 读取用户最新一版状态快照；从未重算过则返回 None。
    async def get_latest(self, *, user_id: UUID) -> AthleteStateSnapshot | None: ...
