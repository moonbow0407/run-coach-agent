"""AgentRun 检查点仓储。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.checkpoint import AgentRunCheckpoint
from app.infrastructure.database.models.agent import AgentRunCheckpointRow
from app.infrastructure.database.session import short_session
from app.infrastructure.jsonutil import json_ready


class SqlAlchemyAgentCheckpointStore:
    """检查点落库：按 (run_id, step_index) 幂等写入，读取取最新 step。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint:
        async with short_session(self._sessions, commit=True) as session:
            existing = await session.scalar(
                select(AgentRunCheckpointRow).where(
                    AgentRunCheckpointRow.run_id == checkpoint.run_id,
                    AgentRunCheckpointRow.step_index == checkpoint.step_index,
                )
            )
            if existing is not None:
                # 同一步重复写入视为幂等：保留首条，避免并发双写炸唯一约束。
                return _from_row(existing)
            row = AgentRunCheckpointRow(
                id=checkpoint.id,
                run_id=checkpoint.run_id,
                turn_id=checkpoint.turn_id,
                user_id=checkpoint.user_id,
                thread_id=checkpoint.thread_id,
                step_index=checkpoint.step_index,
                current_input=checkpoint.current_input,
                interactions=json_ready(list(checkpoint.interactions)),
                discovered_tool_names=json_ready(list(checkpoint.discovered_tool_names)),
                created_at=checkpoint.created_at,
            )
            session.add(row)
            await session.flush()
            return _from_row(row)

    async def get_latest(self, *, user_id: UUID, run_id: UUID) -> AgentRunCheckpoint | None:
        async with short_session(self._sessions) as session:
            row = await session.scalar(
                select(AgentRunCheckpointRow)
                .where(
                    AgentRunCheckpointRow.run_id == run_id,
                    AgentRunCheckpointRow.user_id == user_id,
                )
                .order_by(AgentRunCheckpointRow.step_index.desc())
                .limit(1)
            )
            if row is None:
                return None
            return _from_row(row)


class InMemoryAgentCheckpointStore:
    """单元测试用内存检查点存储。"""

    def __init__(self) -> None:
        self._rows: list[AgentRunCheckpoint] = []

    async def save(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint:
        for existing in self._rows:
            if (
                existing.run_id == checkpoint.run_id
                and existing.step_index == checkpoint.step_index
            ):
                return existing
        self._rows.append(checkpoint)
        return checkpoint

    async def get_latest(self, *, user_id: UUID, run_id: UUID) -> AgentRunCheckpoint | None:
        matches = [row for row in self._rows if row.run_id == run_id and row.user_id == user_id]
        if not matches:
            return None
        return max(matches, key=lambda row: row.step_index)


def _from_row(row: AgentRunCheckpointRow) -> AgentRunCheckpoint:
    return AgentRunCheckpoint(
        id=row.id,
        run_id=row.run_id,
        turn_id=row.turn_id,
        user_id=row.user_id,
        thread_id=row.thread_id,
        step_index=row.step_index,
        current_input=row.current_input,
        interactions=tuple(row.interactions or ()),
        discovered_tool_names=tuple(row.discovered_tool_names or ()),
        created_at=row.created_at,
    )
