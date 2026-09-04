"""Eval 所需的只读 Domain State Adapter。

Eval Core（app.evals）不得直接访问 ORM；所有跨域状态读取（PlanChange /
Plan / Athlete State / Memory 生命周期 / AgentRun 状态）都通过本模块的
只读查询完成。查询一律按 user_id 过滤，保持数据隔离边界。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.domain.plan.models import PlanChangeStatus
from app.infrastructure.database.models.agent import AgentRunRow
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlanChangeRow,
    TrainingPlanRow,
)
from app.infrastructure.database.models.memory import SemanticMemoryRow
from app.infrastructure.database.session import short_session


@dataclass(frozen=True)
class ActivePlanState:
    """当前生效计划的最小读取视图（Eval 评分用）。"""

    plan_id: UUID  # 计划版本实例 ID
    version: int  # 计划版本号
    status: str  # 生命周期状态


@dataclass(frozen=True)
class PlanChangeState:
    """PlanChange 的最小读取视图（Eval 评分用）。"""

    id: UUID
    from_plan_id: UUID  # 基于哪个计划版本提出
    from_plan_version: int  # 提案时的计划版本号
    based_on_state_id: UUID  # 基于哪份跑者状态快照
    based_on_state_version: int  # 提案时的快照版本号
    source_turn_id: UUID | None  # 产生本提案的 Turn
    source_run_id: UUID | None  # 产生本提案的 AgentRun
    status: PlanChangeStatus  # 生命周期状态
    reason: str  # 面向用户的调整理由


@dataclass(frozen=True)
class SemanticMemoryState:
    """语义记忆生命周期状态（Eval 评分用）。"""

    id: UUID
    subject_key: str  # 断言主体键
    value: Any  # 断言值（JSONB 原样）
    content: str  # 自然语言内容
    status: str  # candidate / active / superseded / expired
    superseded_by_id: UUID | None  # 取代者记忆 ID
    valid_from: datetime  # 业务有效期起点


@dataclass(frozen=True)
class AgentRunState:
    """AgentRun 的最小读取视图（EvalTrace 终态校验用）。"""

    id: UUID
    turn_id: UUID
    status: str  # running / completed / failed / cancelled


class EvalCoachingStateReader:
    """Coaching 域只读查询：Active Plan / PlanChange / 版本核对。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_active_plan(self, *, user_id: UUID) -> ActivePlanState | None:
        row = await _first(
            self._sessions,
            select(TrainingPlanRow).where(
                TrainingPlanRow.user_id == user_id,
                TrainingPlanRow.status == "active",
            ),
        )
        if row is None:
            return None
        return ActivePlanState(plan_id=row.id, version=row.version, status=row.status)

    async def get_plan_version(self, *, user_id: UUID, plan_id: UUID) -> int | None:
        row = await _first(
            self._sessions,
            select(TrainingPlanRow).where(
                TrainingPlanRow.user_id == user_id,
                TrainingPlanRow.id == plan_id,
            ),
        )
        return row.version if row is not None else None

    async def get_state_snapshot_version(
        self, *, user_id: UUID, snapshot_id: UUID
    ) -> int | None:
        row = await _first(
            self._sessions,
            select(AthleteStateSnapshotRow).where(
                AthleteStateSnapshotRow.user_id == user_id,
                AthleteStateSnapshotRow.id == snapshot_id,
            ),
        )
        return row.version if row is not None else None

    async def list_plan_changes(self, *, user_id: UUID) -> tuple[PlanChangeState, ...]:
        async with short_session(self._sessions) as session:
            rows = (
                await session.scalars(
                    select(PlanChangeRow).where(PlanChangeRow.user_id == user_id)
                )
            ).all()
            return tuple(_plan_change_state(row) for row in rows)


class EvalMemoryStateReader:
    """Memory 域只读查询：语义记忆生命周期状态。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_semantic_memories(
        self, *, user_id: UUID
    ) -> tuple[SemanticMemoryState, ...]:
        async with short_session(self._sessions) as session:
            rows = (
                await session.scalars(
                    select(SemanticMemoryRow).where(SemanticMemoryRow.user_id == user_id)
                )
            ).all()
            return tuple(
                SemanticMemoryState(
                    id=row.id,
                    subject_key=row.subject_key,
                    value=row.value,
                    content=row.content,
                    status=row.status,
                    superseded_by_id=row.superseded_by_id,
                    valid_from=row.valid_from,
                )
                for row in rows
            )


class EvalAgentStateReader:
    """Agent 执行状态只读查询：AgentRun 终态（供 EvalTrace 校验）。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_run_state(self, *, user_id: UUID, run_id: UUID) -> AgentRunState | None:
        row = await _first(
            self._sessions,
            select(AgentRunRow).where(
                AgentRunRow.id == run_id,
                AgentRunRow.user_id == user_id,
            ),
        )
        if row is None:
            return None
        return AgentRunState(id=row.id, turn_id=row.turn_id, status=row.status)


def _plan_change_state(row) -> PlanChangeState:
    """PlanChange ORM 行 → 只读视图。"""
    return PlanChangeState(
        id=row.id,
        from_plan_id=row.from_plan_id,
        from_plan_version=row.from_plan_version,
        based_on_state_id=row.based_on_state_id,
        based_on_state_version=row.based_on_state_version,
        source_turn_id=row.source_turn_id,
        source_run_id=row.source_run_id,
        status=PlanChangeStatus(row.status),
        reason=row.reason,
    )


async def _first(
    sessions: async_sessionmaker[AsyncSession], stmt: Select
) -> Any:
    """在独立只读短事务里执行查询并返回首行（无行返回 None）。"""
    async with short_session(sessions) as session:
        return (await session.scalars(stmt)).first()
