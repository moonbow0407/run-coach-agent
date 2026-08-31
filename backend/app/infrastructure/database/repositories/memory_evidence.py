"""Approved durable Evidence source 的 user-scoped 读取与状态校验。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.turn import TurnStatus
from app.coaching.domain.plan.models import PlanChangeStatus
from app.common.errors import NotFoundError
from app.infrastructure.database.models.agent import MessageRow, TurnRow
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlanChangeRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.database.models.memory import EpisodeRow
from app.infrastructure.database.session import short_session
from app.memory.domain.episode import EpisodeStatus
from app.memory.domain.evidence import EvidenceIndependenceRole, EvidenceSourceType
from app.memory.ports.evidence_reader import ValidatedEvidence


class SqlAlchemyEvidenceReader:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def read_many(
        self,
        *,
        user_id: UUID,
        source_ids: tuple[tuple[EvidenceSourceType, UUID], ...],
    ) -> tuple[ValidatedEvidence, ...]:
        async with short_session(self._sessions) as session:
            result = [
                await self._read_one(
                    session,
                    user_id=user_id,
                    source_type=source_type,
                    source_id=source_id,
                )
                for source_type, source_id in source_ids
            ]
        return tuple(result)

    async def _read_one(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        source_type: EvidenceSourceType,
        source_id: UUID,
    ) -> ValidatedEvidence:
        if source_type is EvidenceSourceType.MESSAGE:
            row = await session.scalar(
                select(MessageRow)
                .join(TurnRow, TurnRow.id == MessageRow.turn_id)
                .where(
                    MessageRow.id == source_id,
                    TurnRow.user_id == user_id,
                    TurnRow.status == TurnStatus.COMMITTED.value,
                )
            )
            if row is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.created_at,
                    row.created_at.isoformat(),
                    f"conversation:turn:{row.turn_id}",
                    EvidenceIndependenceRole.PRIMARY
                    if row.role == "user"
                    else EvidenceIndependenceRole.DERIVED_CONTEXT,
                    {},
                )
        elif source_type is EvidenceSourceType.TURN:
            row = await session.scalar(
                select(TurnRow).where(
                    TurnRow.id == source_id,
                    TurnRow.user_id == user_id,
                    TurnRow.status == TurnStatus.COMMITTED.value,
                )
            )
            if row is not None and row.committed_at is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.committed_at,
                    row.committed_at.isoformat(),
                    f"conversation:turn:{row.id}",
                    EvidenceIndependenceRole.DERIVED_CONTEXT,
                    {},
                )
        elif source_type is EvidenceSourceType.WORKOUT:
            row = await session.scalar(
                select(WorkoutRow).where(WorkoutRow.id == source_id, WorkoutRow.user_id == user_id)
            )
            if row is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.started_at,
                    row.created_at.isoformat(),
                    f"training:workout:{row.id}",
                    EvidenceIndependenceRole.PRIMARY,
                    {
                        "workout_type": row.workout_type,
                        "distance_m": row.distance_m,
                        "duration_s": row.duration_s,
                    },
                )
        elif source_type is EvidenceSourceType.WORKOUT_FEEDBACK:
            row = await session.scalar(
                select(WorkoutFeedbackRow).where(
                    WorkoutFeedbackRow.id == source_id,
                    WorkoutFeedbackRow.user_id == user_id,
                )
            )
            if row is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.created_at,
                    row.created_at.isoformat(),
                    f"training:workout:{row.workout_id}",
                    EvidenceIndependenceRole.PRIMARY,
                    {
                        "subjective_fatigue": row.subjective_fatigue,
                        "perceived_exertion": row.perceived_exertion,
                        "soreness": row.soreness,
                    },
                )
        elif source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT:
            row = await session.scalar(
                select(AthleteStateSnapshotRow).where(
                    AthleteStateSnapshotRow.id == source_id,
                    AthleteStateSnapshotRow.user_id == user_id,
                )
            )
            if row is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.as_of,
                    f"{row.version}:{row.algorithm_version}:{row.created_at.isoformat()}",
                    f"state:snapshot:{row.id}",
                    EvidenceIndependenceRole.DERIVED_CONTEXT,
                    {
                        "fatigue_level": row.fatigue_level,
                        "recovery_level": row.recovery_level,
                        "confidence": row.confidence,
                    },
                )
        elif source_type is EvidenceSourceType.PLAN_CHANGE:
            row = await session.scalar(
                select(PlanChangeRow).where(
                    PlanChangeRow.id == source_id,
                    PlanChangeRow.user_id == user_id,
                    PlanChangeRow.status == PlanChangeStatus.CONFIRMED.value,
                )
            )
            if row is not None and row.resolved_at is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.resolved_at,
                    row.resolved_at.isoformat(),
                    f"plan_change:{row.id}",
                    EvidenceIndependenceRole.PRIMARY,
                    {"change_type": row.change_type, "reason": row.reason},
                )
        elif source_type is EvidenceSourceType.EPISODE:
            row = await session.scalar(
                select(EpisodeRow).where(
                    EpisodeRow.id == source_id,
                    EpisodeRow.user_id == user_id,
                    EpisodeRow.status == EpisodeStatus.COMPLETED.value,
                )
            )
            if row is not None and row.completed_at is not None:
                return ValidatedEvidence(
                    source_type,
                    row.id,
                    row.ended_at,
                    row.completed_at.isoformat(),
                    f"episode:{row.id}",
                    EvidenceIndependenceRole.PRIMARY,
                    {"type": row.type, "summary": row.summary},
                )
        raise NotFoundError("memory_evidence_source_not_found")
