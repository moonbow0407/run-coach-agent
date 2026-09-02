"""PlanChange 仓储端口：计划调整提案的读写与 CAS 状态流转。"""

from datetime import datetime
from typing import Protocol  # Protocol：结构化鸭子类型，只约束方法签名，不要求继承
from uuid import UUID

from app.coaching.domain.plan.models import PlanChange, PlanChangeStatus


class PlanChangeRepository(Protocol):
    """计划调整提案的持久化接口；所有操作按 user_id 隔离。"""

    async def get(self, *, user_id: UUID, plan_change_id: UUID) -> PlanChange | None:
        """按 id 读取提案；不存在或不属于该用户返回 None。"""
        ...

    async def get_unresolved(self, *, user_id: UUID) -> PlanChange | None:
        """读取尚未进入终态的提案（DRAFT / 待确认）；同用户最多一个。"""
        ...

    async def get_pending(self, *, user_id: UUID) -> PlanChange | None:
        """读取等待用户确认（PENDING_CONFIRMATION）的提案。"""
        ...

    async def list_by_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
    ) -> list[PlanChange]:
        """列出某轮对话（Turn）产生的全部提案，供终态收尾使用。"""
        ...

    async def add(self, plan_change: PlanChange) -> PlanChange:
        """持久化新建提案（初始状态 DRAFT）。"""
        ...

    async def transition(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        expected: PlanChangeStatus,
        target: PlanChangeStatus,
        resolved_at: datetime | None = None,
        resulting_plan_id: UUID | None = None,
    ) -> PlanChange:
        """CAS 状态转换：在用户行锁下仅当当前状态 == expected 才写入 target。

        拒绝 stale read + last-write-wins；当前状态不符时抛 ConflictError，
        由调用方决定幂等返回还是上报冲突。confirm 的 CONFIRMED 写入属于
        PlanActivationStore 的原子激活事务，不走本方法。
        """
        ...
