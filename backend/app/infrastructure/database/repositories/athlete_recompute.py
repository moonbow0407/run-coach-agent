"""Athlete State evidence read、评估提交与 Outbox 的单用户锁事务。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.contracts.durable_events import (
    AthleteStateRecomputedV1,
    new_athlete_state_recomputed_event,
)
from app.coaching.domain.athlete.evaluator import AthleteStateAssessment
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_recompute_uow import (
    AthleteStateEvidenceSet,
    AthleteStateRecomputeTransaction,
    AthleteStateTrigger,
    AthleteStateTriggerType,
)
from app.common.errors import DomainError, NotFoundError
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.locking import lock_user_row
from app.infrastructure.database.mappers import (
    athlete_state_from_row,
    feedback_from_row,
    signals_to_json,
    workout_from_row,
)
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.outbox.writer import OutboxWriter

_EVIDENCE_LOOKBACK = timedelta(days=14)  # 证据回看窗口：状态评估只看最近 14 天的训练与反馈


class SqlAlchemyAthleteStateRecomputeUnitOfWork:
    """跑者状态重算的工作单元：一个用户一次评估 = 一个行锁事务。"""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
    ) -> None:
        self._sessions = sessions
        self._outbox = outbox

    @asynccontextmanager
    async def transaction(
        self,
        *,
        user_id: UUID,
    ) -> AsyncIterator[AthleteStateRecomputeTransaction]:
        # asynccontextmanager：异步上下文管理器，进入时开事务加用户行锁，正常退出才提交。
        async with self._sessions() as session:
            try:
                await lock_user_row(session, user_id)  # 用户维度行锁，串行化同一用户的状态重算
                yield _SqlAlchemyAthleteStateRecomputeTransaction(
                    session=session,
                    outbox=self._outbox,
                    user_id=user_id,
                )
                await session.commit()  # 块内全部成功才提交：快照与事件同事务落库
            except BaseException:
                await session.rollback()  # 任何异常都回滚，不留下半成品状态
                raise


class _SqlAlchemyAthleteStateRecomputeTransaction:
    """单个重算事务内的读证据 / 追加快照操作集合。"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        outbox: OutboxWriter,
        user_id: UUID,
    ) -> None:
        self._session = session
        self._outbox = outbox
        self._user_id = user_id

    async def load_evidence(
        self,
        *,
        trigger: AthleteStateTrigger | None,
        trigger_available_at: datetime,
        observed_at: datetime,
    ) -> AthleteStateEvidenceSet:
        """加载评估所需的证据集：最新快照 + 截止点前 14 天的训练与反馈。"""
        if trigger is not None:
            await self._validate_trigger(trigger)  # 先校验触发源真实且属于本用户
        latest_row = await self._session.scalar(  # 取最高版本的已有快照，供增量评估
            select(AthleteStateSnapshotRow)
            .where(AthleteStateSnapshotRow.user_id == self._user_id)
            .order_by(AthleteStateSnapshotRow.version.desc())
            .limit(1)
        )
        workout_cutoff = await self._session.scalar(  # 最近一次训练数据更新时间
            select(func.max(WorkoutRow.updated_at)).where(
                WorkoutRow.user_id == self._user_id,
                WorkoutRow.updated_at <= observed_at,
            )
        )
        feedback_cutoff = await self._session.scalar(  # 最近一次反馈数据更新时间
            select(func.max(WorkoutFeedbackRow.updated_at)).where(
                WorkoutFeedbackRow.user_id == self._user_id,
                WorkoutFeedbackRow.updated_at <= observed_at,
            )
        )
        cutoff = max(  # 以触发时间与两类数据最新更新时间的最大值为评估截止点
            moment
            for moment in (trigger_available_at, workout_cutoff, feedback_cutoff)
            if moment is not None
        )
        start = cutoff - _EVIDENCE_LOOKBACK  # 只回看 14 天窗口
        workout_rows = (
            await self._session.scalars(
                select(WorkoutRow)
                .where(
                    WorkoutRow.user_id == self._user_id,
                    WorkoutRow.updated_at <= observed_at,
                    WorkoutRow.started_at >= start,
                    WorkoutRow.started_at <= cutoff,
                )
                .order_by(WorkoutRow.started_at.asc(), WorkoutRow.id.asc())
            )
        ).all()
        workout_ids = [row.id for row in workout_rows]
        feedback_rows: tuple[WorkoutFeedbackRow, ...] = ()
        if workout_ids:  # 没有训练记录就无需查反馈
            feedback_rows = tuple(
                (
                    await self._session.scalars(
                        select(WorkoutFeedbackRow)
                        .where(
                            WorkoutFeedbackRow.user_id == self._user_id,
                            WorkoutFeedbackRow.workout_id.in_(workout_ids),
                            WorkoutFeedbackRow.updated_at <= cutoff,
                        )
                        .order_by(
                            WorkoutFeedbackRow.created_at.asc(),
                            WorkoutFeedbackRow.id.asc(),
                        )
                    )
                ).all()
            )
        return AthleteStateEvidenceSet(
            latest_snapshot=(
                athlete_state_from_row(latest_row) if latest_row is not None else None
            ),
            workouts=tuple(workout_from_row(row) for row in workout_rows),
            feedback=tuple(feedback_from_row(row) for row in feedback_rows),
            cutoff=cutoff,
        )

    async def _validate_trigger(self, trigger: AthleteStateTrigger) -> None:
        """在用户锁内重读 source；跨用户、被删除或篡改事件都永久失败。"""
        if trigger.source_type is AthleteStateTriggerType.WORKOUT:
            row = await self._session.scalar(  # 重读触发源训练，确认存在且属于本用户
                select(WorkoutRow).where(
                    WorkoutRow.id == trigger.source_id,
                    WorkoutRow.user_id == self._user_id,
                )
            )
            if row is None:
                raise NotFoundError("canonical_workout_source_not_found")  # 源被删除：事件无法兑现
        else:
            row = await self._session.scalar(  # 反馈触发源：校验存在且归属正确
                select(WorkoutFeedbackRow).where(
                    WorkoutFeedbackRow.id == trigger.source_id,
                    WorkoutFeedbackRow.user_id == self._user_id,
                )
            )
            if row is None:
                raise NotFoundError("canonical_feedback_source_not_found")
            if trigger.workout_id is None or row.workout_id != trigger.workout_id:  # 事件声称的关联训练与实际不符
                raise DomainError("canonical_source_identity_mismatch")
        if row.updated_at < trigger.available_at:  # 源数据比事件还旧：消息滞后或被篡改
            raise DomainError("canonical_source_version_mismatch")

    async def append_snapshot(
        self,
        *,
        as_of: datetime,
        assessment: AthleteStateAssessment,
        created_at: datetime,
        event_metadata: EventMetadata,
    ) -> AthleteStateSnapshot:
        """追加一条新版本状态快照，并向 outbox 写入重算完成事件。"""
        latest_version = await self._session.scalar(  # 快照只追加不覆盖：新版本号 = 旧最大 + 1
            select(func.max(AthleteStateSnapshotRow.version)).where(
                AthleteStateSnapshotRow.user_id == self._user_id
            )
        )
        row = AthleteStateSnapshotRow(
            id=new_id(),
            user_id=self._user_id,
            version=(latest_version or 0) + 1,
            as_of=as_of,
            fatigue_level=(
                assessment.fatigue_level.value if assessment.fatigue_level else None
            ),
            recovery_level=(
                assessment.recovery_level.value if assessment.recovery_level else None
            ),
            recent_training_load=assessment.recent_training_load,
            workout_completion_rate=assessment.workout_completion_rate,
            training_load_coverage=assessment.training_load_coverage,
            signals=signals_to_json(assessment.signals),
            confidence=assessment.confidence,
            algorithm_version=assessment.algorithm_version,
            created_at=created_at,
        )
        self._session.add(row)
        self._outbox.add(  # 业务数据与待发布事件同事务落库（outbox 模式）
            self._session,
            new_athlete_state_recomputed_event(
                user_id=self._user_id,
                payload=AthleteStateRecomputedV1(
                    snapshot_id=row.id,
                    snapshot_version=row.version,
                    as_of=as_of,
                    algorithm_version=assessment.algorithm_version,
                ),
                metadata=event_metadata,
            ),
        )
        await self._session.flush()  # 提前拿到数据库生成的默认值并暴露约束冲突
        return athlete_state_from_row(row)
