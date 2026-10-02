"""计划调整应用服务：生成 DRAFT、生命周期流转、确认 / 拒绝。"""

from datetime import datetime
from uuid import UUID

from app.coaching.application.errors import StalePlanChangeError
from app.coaching.domain.plan.adaptation import generate_reduce_upcoming_load
from app.coaching.domain.plan.models import (
    PlanChange,
    PlanChangeStatus,
    PlanChangeType,
)
from app.coaching.ports.athlete_state_repository import AthleteStateRepository
from app.coaching.ports.plan_activation_store import PlanActivationResult, PlanActivationStore
from app.coaching.ports.plan_change_repository import PlanChangeRepository
from app.coaching.ports.plan_repository import PlanRepository
from app.common.clock import Clock
from app.common.errors import ConflictError, DomainError, NotFoundError
from app.common.events import EventMetadata
from app.common.ids import new_id


class PlanAdaptationService:
    """计划调整应用服务：生成 DRAFT 提案、生命周期流转、确认激活与拒绝。"""

    def __init__(
        self,
        *,
        plans: PlanRepository,
        snapshots: AthleteStateRepository,
        changes: PlanChangeRepository,
        activation: PlanActivationStore,
        clock: Clock,
    ) -> None:
        self._plans = plans
        self._snapshots = snapshots
        self._changes = changes
        self._activation = activation
        self._clock = clock

    async def propose_reduce_upcoming_load(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        run_id: UUID,
        as_of: datetime,
        based_on_plan_version: int,
        based_on_state_version: int,
        horizon_days: int,
        reason: str,
    ) -> tuple[PlanChange, bool]:
        """创建 DRAFT PlanChange。返回 (提案, 窗口内是否有未改动的 Race)。"""
        # 调整理由必填：它是给用户看的解释，不允许空白。
        if not reason.strip():
            raise DomainError("reason_required")
        # 同一用户同时只允许一个未解决提案，避免多个草案互相覆盖。
        unresolved = await self._changes.get_unresolved(user_id=user_id)
        if unresolved is not None:
            raise ConflictError("unresolved_plan_change_exists")
        plan = await self._plans.get_active(user_id=user_id)
        if plan is None:
            raise DomainError("no_active_plan")
        # 乐观版本核对：调用方必须基于它读到的计划 / 状态版本发起提案。
        if plan.version != based_on_plan_version:
            raise DomainError("based_on_plan_version_mismatch")
        state = await self._snapshots.get_latest(user_id=user_id)
        if state is None:
            raise DomainError("no_athlete_state")
        if state.version != based_on_state_version:
            raise DomainError("based_on_state_version_mismatch")
        # 课次 diff 由纯领域函数生成，模型不直接提供 diff。
        sessions = await self._plans.list_sessions(user_id=user_id, plan_id=plan.id)
        generated = generate_reduce_upcoming_load(
            as_of=as_of,
            horizon_days=horizon_days,
            sessions=sessions,
            fatigue_level=state.fatigue_level,
            recovery_level=state.recovery_level,
        )
        # 先在内存中组装 DRAFT 提案再落库；激活要等用户确认。
        change = PlanChange(
            id=new_id(),
            user_id=user_id,
            from_plan_id=plan.id,
            from_plan_version=plan.version,
            based_on_state_id=state.id,
            based_on_state_version=state.version,
            source_turn_id=turn_id,
            source_run_id=run_id,
            as_of=as_of,
            change_type=PlanChangeType.REDUCE_UPCOMING_LOAD,
            payload=generated.payload,
            reason=reason,
            status=PlanChangeStatus.DRAFT,
            created_at=self._clock.now(),
            resolved_at=None,
            resulting_plan_id=None,
        )
        stored = await self._changes.add(change)
        return stored, generated.race_session_not_modified

    async def get(self, *, user_id: UUID, plan_change_id: UUID) -> PlanChange:
        change = await self._changes.get(user_id=user_id, plan_change_id=plan_change_id)
        if change is None:
            raise NotFoundError("计划调整不存在")
        return change

    async def get_unresolved(self, *, user_id: UUID) -> PlanChange:
        """读取该用户唯一未解决的提案，包含 DRAFT 与待确认状态。"""
        change = await self._changes.get_unresolved(user_id=user_id)
        if change is None:
            raise NotFoundError("没有未解决的计划调整")
        return change

    async def get_pending(self, *, user_id: UUID) -> PlanChange:
        """只读取真正等待用户确认的提案，不暴露 DRAFT。"""
        change = await self._changes.get_pending(user_id=user_id)
        if change is None:
            raise NotFoundError("没有待确认的计划调整")
        return change

    async def promote_draft_for_turn(self, *, user_id: UUID, turn_id: UUID) -> None:
        """Turn 已提交（COMMITTED）：把该轮产生的 DRAFT 推进到待确认。"""
        for change in await self._changes.list_by_turn(user_id=user_id, turn_id=turn_id):
            if change.status is PlanChangeStatus.DRAFT:
                await self._changes.transition(
                    user_id=user_id,
                    plan_change_id=change.id,
                    expected=PlanChangeStatus.DRAFT,
                    target=PlanChangeStatus.PENDING_CONFIRMATION,
                )

    async def abandon_draft_for_turn(self, *, user_id: UUID, turn_id: UUID) -> None:
        """Turn 被拒绝或中止：该轮产生的 DRAFT 直接作废。"""
        now = self._clock.now()
        for change in await self._changes.list_by_turn(user_id=user_id, turn_id=turn_id):
            if change.status is PlanChangeStatus.DRAFT:
                await self._changes.transition(
                    user_id=user_id,
                    plan_change_id=change.id,
                    expected=PlanChangeStatus.DRAFT,
                    target=PlanChangeStatus.ABANDONED,
                    resolved_at=now,
                )

    async def confirm(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        event_metadata: EventMetadata | None = None,
    ) -> PlanActivationResult:
        """用户确认提案：由激活存储在行锁事务内完成校验与版本激活。"""
        change = await self._changes.get(user_id=user_id, plan_change_id=plan_change_id)
        if change is None:
            raise NotFoundError("计划调整不存在")
        try:
            return await self._activation.confirm(
                user_id=user_id,
                plan_change_id=plan_change_id,
                now=self._clock.now(),
                event_metadata=event_metadata or EventMetadata(correlation_id=new_id()),
            )
        except ConflictError as exc:
            # 存储层判定版本过期（stale）：重读提案并归一化为 StalePlanChangeError。
            if exc.code == "stale":
                stale = await self._changes.get(user_id=user_id, plan_change_id=plan_change_id)
                if stale is None:
                    raise NotFoundError("计划调整不存在") from exc
                raise StalePlanChangeError(stale) from exc
            raise

    async def reject(self, *, user_id: UUID, plan_change_id: UUID) -> PlanChange:
        """用户拒绝提案：PENDING → REJECTED；已是 REJECTED 则幂等返回。"""
        change = await self._changes.get(user_id=user_id, plan_change_id=plan_change_id)
        if change is None:
            raise NotFoundError("计划调整不存在")
        # 幂等：重复拒绝直接返回现有结果，不报错。
        if change.status is PlanChangeStatus.REJECTED:
            return change
        try:
            return await self._changes.transition(
                user_id=user_id,
                plan_change_id=plan_change_id,
                expected=PlanChangeStatus.PENDING_CONFIRMATION,
                target=PlanChangeStatus.REJECTED,
                resolved_at=self._clock.now(),
            )
        except ConflictError:
            # CAS 失败：读取到的 PENDING 已被并发 confirm / reject 等改写。
            # 重新读取给出准确结果，绝不覆盖已生效的终态。
            current = await self._changes.get(user_id=user_id, plan_change_id=plan_change_id)
            if current is not None and current.status is PlanChangeStatus.REJECTED:
                return current
            raise ConflictError("plan_change_not_rejectable") from None
