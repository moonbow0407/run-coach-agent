"""Conversation 仓储：Thread / Turn / Message / AgentRun 的读写实现。

SqlAlchemyConversationStore 拥有 Conversation 生命周期事务（ARCHITECTURE §44）：
start_turn 与 commit_turn 各是一次短事务，推理循环本身不持有数据库事务。
SqlAlchemyConversationReader 只暴露已提交消息，供历史查询与上下文装配使用。
"""

from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.message import Message, MessageRole
from app.agent.models.run import AgentRunStatus
from app.agent.models.thread import Thread
from app.agent.models.turn import TurnStatus
from app.agent.ports.conversation_reader import CommittedTurnMessages
from app.agent.ports.conversation_store import CommittedTurn, StartedTurn
from app.common.clock import Clock
from app.common.errors import ForbiddenError, NotFoundError
from app.common.ids import new_id
from app.infrastructure.database.mappers import (
    message_from_row,
    run_from_row,
    thread_from_row,
    turn_from_row,
)
from app.infrastructure.database.models.agent import AgentRunRow, MessageRow, ThreadRow, TurnRow
from app.infrastructure.database.session import short_session


class SqlAlchemyConversationStore:
    """ConversationStore 端口的 SQL 实现；写路径按短事务组织。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def start_turn(
        self,
        *,
        user_id: UUID,
        thread_id: UUID | None,
        content: str,
    ) -> StartedTurn:
        """事务 A：新建（或校验）Thread + Turn + 用户消息 + AgentRun，一次提交。"""
        now = self._clock.now()
        turn_id = new_id()
        message_id = new_id()
        run_id = new_id()

        async with short_session(self._sessions, commit=True) as session:
            if thread_id is None:
                thread = ThreadRow(
                    id=new_id(),
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(thread)
                await session.flush()
            else:
                thread = await self._require_thread(
                    session,
                    user_id=user_id,
                    thread_id=thread_id,
                )

            turn_row = TurnRow(
                id=turn_id,
                thread_id=thread.id,
                user_id=user_id,
                user_message_id=message_id,
                assistant_message_id=None,
                status=TurnStatus.PENDING.value,
                started_at=now,
                committed_at=None,
            )
            session.add(turn_row)
            await session.flush()

            message_row = MessageRow(
                id=message_id,
                thread_id=thread.id,
                turn_id=turn_id,
                role=MessageRole.USER.value,
                content=content,
                created_at=now,
            )
            session.add(message_row)

            run_row = AgentRunRow(
                id=run_id,
                turn_id=turn_id,
                user_id=user_id,
                status=AgentRunStatus.RUNNING.value,
                started_at=now,
                completed_at=None,
            )
            session.add(run_row)

            turn_row.status = TurnStatus.RUNNING.value
            thread.updated_at = now
            await session.flush()

            return StartedTurn(
                thread=thread_from_row(thread),
                turn=turn_from_row(turn_row),
                user_message=message_from_row(message_row),
                run=run_from_row(run_row),
            )

    async def commit_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        assistant_content: str,
    ) -> CommittedTurn:
        """事务 B：写入助手消息，Turn -> committed、AgentRun -> completed。"""
        now = self._clock.now()
        assistant_id = new_id()

        async with short_session(self._sessions, commit=True) as session:
            turn_row, run_row, thread_row = await self._require_open_turn(
                session,
                user_id=user_id,
                turn_id=turn_id,
            )

            assistant_row = MessageRow(
                id=assistant_id,
                thread_id=turn_row.thread_id,
                turn_id=turn_row.id,
                role=MessageRole.ASSISTANT.value,
                content=assistant_content,
                created_at=now,
            )
            session.add(assistant_row)

            turn_row.assistant_message_id = assistant_id
            turn_row.status = TurnStatus.COMMITTED.value
            turn_row.committed_at = now
            run_row.status = AgentRunStatus.COMPLETED.value
            run_row.completed_at = now
            thread_row.updated_at = now
            await session.flush()

            return CommittedTurn(
                thread=thread_from_row(thread_row),
                turn=turn_from_row(turn_row),
                assistant_message=message_from_row(assistant_row),
                run=run_from_row(run_row),
            )

    async def fail_turn(self, *, user_id: UUID, turn_id: UUID) -> None:
        """把仍处于打开状态的 Turn / AgentRun 置为 failed。"""
        await self._finish_unsuccessfully(
            user_id=user_id,
            turn_id=turn_id,
            turn_status=TurnStatus.FAILED,
            run_status=AgentRunStatus.FAILED,
        )

    async def cancel_turn(self, *, user_id: UUID, turn_id: UUID) -> None:
        """把仍处于打开状态的 Turn / AgentRun 置为 cancelled。"""
        await self._finish_unsuccessfully(
            user_id=user_id,
            turn_id=turn_id,
            turn_status=TurnStatus.CANCELLED,
            run_status=AgentRunStatus.CANCELLED,
        )

    async def _finish_unsuccessfully(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        turn_status: TurnStatus,
        run_status: AgentRunStatus,
    ) -> None:
        now = self._clock.now()
        async with short_session(self._sessions, commit=True) as session:
            turn_row, run_row, thread_row = await self._require_open_turn(
                session,
                user_id=user_id,
                turn_id=turn_id,
            )
            turn_row.status = turn_status.value
            run_row.status = run_status.value
            run_row.completed_at = now
            thread_row.updated_at = now

    async def _require_thread(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> ThreadRow:
        row = await session.get(ThreadRow, thread_id)
        if row is None:
            raise NotFoundError("对话线程不存在")
        if row.user_id != user_id:
            raise ForbiddenError("无权访问该对话线程")
        return row

    async def _require_open_turn(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        turn_id: UUID,
    ) -> tuple[TurnRow, AgentRunRow, ThreadRow]:
        turn_row = await session.get(TurnRow, turn_id)
        if turn_row is None:
            raise NotFoundError("Turn 不存在")
        if turn_row.user_id != user_id:
            raise ForbiddenError("无权访问该 Turn")
        if turn_row.status not in {TurnStatus.PENDING.value, TurnStatus.RUNNING.value}:
            raise ForbiddenError(f"Turn 当前状态不可收尾: {turn_row.status}")

        run_row = await session.scalar(select(AgentRunRow).where(AgentRunRow.turn_id == turn_id))
        if run_row is None:
            raise NotFoundError("AgentRun 不存在")

        thread_row = await self._require_thread(
            session,
            user_id=user_id,
            thread_id=turn_row.thread_id,
        )
        return turn_row, run_row, thread_row


class SqlAlchemyConversationReader:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_thread(self, *, user_id: UUID, thread_id: UUID) -> Thread | None:
        async with short_session(self._sessions) as session:
            row = await session.get(ThreadRow, thread_id)
            if row is None or row.user_id != user_id:
                return None
            return thread_from_row(row)

    async def list_committed_messages(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID | None,
        limit: int,
    ) -> list[Message]:
        """按时间正序返回已提交消息。

        只取 Turn 状态为 committed 的消息，failed / cancelled 的 Turn
        不会污染正常上下文；先按时间倒序取最近 limit 条再反转回正序。
        """
        # 同一秒内 user / assistant 可能共享 created_at（测试 Clock 冻结时尤其如此）。
        # 按 Turn 开始时间 + user 先于 assistant 给出稳定的 Canonical 顺序。
        role_rank = case((MessageRow.role == MessageRole.USER.value, 0), else_=1)
        stmt = (
            select(MessageRow)
            .join(TurnRow, TurnRow.id == MessageRow.turn_id)
            .where(
                MessageRow.thread_id == thread_id,
                TurnRow.user_id == user_id,
                TurnRow.status == TurnStatus.COMMITTED.value,
            )
            .order_by(TurnRow.started_at.desc(), role_rank.desc(), MessageRow.created_at.desc())
            .limit(limit)
        )
        if exclude_turn_id is not None:
            stmt = stmt.where(TurnRow.id != exclude_turn_id)

        async with short_session(self._sessions) as session:
            rows = list((await session.scalars(stmt)).all())
            rows.reverse()
            return [message_from_row(row) for row in rows]

    async def get_committed_turn_messages(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
    ) -> CommittedTurnMessages | None:
        """读取一个已提交 Turn 的 canonical user / assistant 消息。"""
        turn_stmt = select(TurnRow).where(
            TurnRow.id == turn_id,
            TurnRow.user_id == user_id,
            TurnRow.status == TurnStatus.COMMITTED.value,
        )
        async with short_session(self._sessions) as session:
            turn = await session.scalar(turn_stmt)
            if turn is None or turn.assistant_message_id is None or turn.committed_at is None:
                return None
            rows = list(
                (
                    await session.scalars(
                        select(MessageRow).where(
                            MessageRow.turn_id == turn_id,
                            MessageRow.id.in_((turn.user_message_id, turn.assistant_message_id)),
                        )
                    )
                ).all()
            )
            by_id = {row.id: row for row in rows}
            if turn.user_message_id not in by_id or turn.assistant_message_id not in by_id:
                return None
            user_message = message_from_row(by_id[turn.user_message_id])
            assistant_message = message_from_row(by_id[turn.assistant_message_id])
            if (
                user_message.role is not MessageRole.USER
                or assistant_message.role is not MessageRole.ASSISTANT
            ):
                return None
            return CommittedTurnMessages(
                turn_id=turn.id,
                user_message=user_message,
                assistant_message=assistant_message,
                committed_at=turn.committed_at,
            )
