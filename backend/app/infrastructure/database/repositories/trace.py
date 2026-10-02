"""执行轨迹仓储：把 RunStep 写入 run_steps 表。

每条轨迹独立短事务；index 由“当前最大值 + 1”生成，
保证同一 AgentRun 内步骤顺序稳定（架构不使用数据库序列）。
ToolCall RunStep 保存 Tool name、arguments 与 model_call_id；
对应 Observation RunStep 通过 model_dump 携带同一 model_call_id；
两条 RunStep 由内部 UUID call_id 关联（与模型协议 ID 不混用）。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.context.bundle import ContextManifest
from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.observation import Observation
from app.agent.models.run import RunStep, RunStepKind
from app.common.clock import Clock
from app.common.errors import NotFoundError
from app.common.ids import new_id
from app.infrastructure.database.models.agent import AgentRunRow, RunStepRow
from app.infrastructure.database.session import short_session
from app.infrastructure.jsonutil import json_ready


class SqlAlchemyAgentTraceRecorder:
    """执行轨迹记录器：Agent 每一步（上下文/推理/调用/观察/终答）落一行轨迹。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def record_context(self, *, run_id: UUID, manifest: ContextManifest) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.CONTEXT,
            call_id=None,
            # 清单只含 ID / 版本与裁剪元数据，不含 Prompt 与记忆正文。
            input_data=json_ready(vars(manifest)),
            output_data=None,
            started_at=now,
            completed_at=now,
        )

    async def record_reasoning(
        self,
        *,
        run_id: UUID,
        action_type: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.REASONING,
            call_id=None,
            input_data=None,
            output_data=json_ready({"action_type": action_type, "metadata": metadata or {}}),
            started_at=now,
            completed_at=now,
        )

    async def record_action(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        action: ToolCallAction,
    ) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.TOOL_CALL,
            call_id=call_id,
            input_data=json_ready(
                {
                    "tool": action.tool,
                    "arguments": action.arguments,
                    "model_call_id": action.model_call_id,
                }
            ),
            output_data=None,
            started_at=now,
            completed_at=now,
        )

    async def record_observation(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        observation: Observation,
    ) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.OBSERVATION,
            call_id=call_id,
            input_data=None,
            output_data=json_ready(observation.model_dump()),
            started_at=now,
            completed_at=now,
        )

    async def record_final(self, *, run_id: UUID, action: FinalAction) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.FINAL,
            call_id=None,
            input_data=None,
            output_data=json_ready({"content": action.content}),
            started_at=now,
            completed_at=now,
        )

    async def _insert(
        self,
        *,
        run_id: UUID,
        kind: RunStepKind,
        call_id: UUID | None,
        input_data: dict[str, Any] | None,
        output_data: dict[str, Any] | None,
        started_at: datetime,
        completed_at: datetime | None,
    ) -> None:
        """独立短事务写入一条轨迹；index 取当前最大值 + 1 保证顺序。"""
        async with short_session(self._sessions, commit=True) as session:
            current = await session.scalar(
                select(func.max(RunStepRow.index)).where(RunStepRow.run_id == run_id)
            )
            index = int(current or 0) + 1
            session.add(
                RunStepRow(
                    id=new_id(),
                    run_id=run_id,
                    index=index,
                    kind=kind.value,
                    call_id=call_id,
                    input_data=input_data,
                    output_data=output_data,
                    started_at=started_at,
                    completed_at=completed_at,
                )
            )


class SqlAlchemyAgentTraceReader:
    """执行轨迹只读读取器：先校验 run 归属用户，再按 index 返回领域 RunStep。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_steps(self, *, user_id: UUID, run_id: UUID) -> tuple[RunStep, ...]:
        async with short_session(self._sessions) as session:
            # 归属校验：run 不存在或不属于该用户统一 not-found，不泄漏存在性。
            run_row = await session.scalar(
                select(AgentRunRow).where(
                    AgentRunRow.id == run_id,
                    AgentRunRow.user_id == user_id,
                )
            )
            if run_row is None:
                raise NotFoundError("AgentRun 不存在")
            rows = (
                await session.scalars(
                    select(RunStepRow)
                    .where(RunStepRow.run_id == run_id)
                    .order_by(RunStepRow.index.asc())
                )
            ).all()
            return tuple(_run_step_from_row(row) for row in rows)


def _run_step_from_row(row: RunStepRow) -> RunStep:
    """RunStep ORM 行 → 领域对象的字段映射。"""
    return RunStep(
        id=row.id,
        run_id=row.run_id,
        index=row.index,
        kind=RunStepKind(row.kind),
        call_id=row.call_id,
        input_data=row.input_data,
        output_data=row.output_data,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )
