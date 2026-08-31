"""PostgreSQL + pgvector Memory repository。

Projection 的 receipt、Memory / Episode、Evidence 与 supersession 在同一
用户行锁短事务提交；LLM 与 embedding 必须在进入本类前完成。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.ids import new_id
from app.infrastructure.database.locking import lock_user_row
from app.infrastructure.database.models.memory import (
    EpisodeEvidenceRow,
    EpisodeRow,
    MemoryEvidenceRow,
    MemoryProjectionRunRow,
    SemanticMemoryRow,
)
from app.infrastructure.database.session import short_session
from app.memory.domain.episode import Episode, EpisodeCandidate, EpisodeStatus, EpisodeType
from app.memory.domain.lifecycle import candidate_precedes_active
from app.memory.domain.semantic import (
    MemoryOrigin,
    SemanticMemory,
    SemanticMemoryCandidate,
    SemanticMemoryStatus,
    SemanticMemoryType,
)
from app.memory.ports.repositories import (
    ProjectionResult,
    RankedEpisodeCandidate,
    RankedSemanticCandidate,
)


class SqlAlchemyMemoryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def apply_semantic_projection(
        self,
        *,
        user_id: UUID,
        projector_name: str,
        projector_version: str,
        projection_key: str,
        input_fingerprint: str,
        input_checkpoint: dict[str, object],
        candidates: tuple[SemanticMemoryCandidate, ...],
        embeddings: tuple[tuple[float, ...], ...],
        embedding_model: str,
        embedding_version: str,
        now: datetime,
    ) -> ProjectionResult:
        if len(candidates) != len(embeddings):
            raise ValueError("candidate_embedding_count_mismatch")
        async with short_session(self._sessions, commit=True) as session:
            await lock_user_row(session, user_id)
            receipt = await self._get_receipt(
                session,
                user_id=user_id,
                projector_name=projector_name,
                projector_version=projector_version,
                projection_key=projection_key,
            )
            if (
                receipt is not None
                and receipt.status == "completed"
                and receipt.input_fingerprint == input_fingerprint
            ):
                return ProjectionResult(
                    projection_key=projection_key,
                    result_ids=tuple(
                        UUID(value) for value in receipt.result_summary.get("ids", [])
                    ),
                    replayed=True,
                )

            result_ids: list[UUID] = []
            for candidate, embedding in zip(candidates, embeddings, strict=True):
                memory_id = await self._merge_semantic(
                    session,
                    user_id=user_id,
                    candidate=candidate,
                    embedding=embedding,
                    embedding_model=embedding_model,
                    embedding_version=embedding_version,
                    projector_name=projector_name,
                    projector_version=projector_version,
                    now=now,
                )
                result_ids.append(memory_id)
            self._complete_receipt(
                session,
                receipt=receipt,
                user_id=user_id,
                projector_name=projector_name,
                projector_version=projector_version,
                projection_key=projection_key,
                input_fingerprint=input_fingerprint,
                input_checkpoint=input_checkpoint,
                result_ids=result_ids,
                now=now,
            )
            await session.flush()
            return ProjectionResult(
                projection_key=projection_key,
                result_ids=tuple(result_ids),
                replayed=False,
            )

    async def _merge_semantic(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        candidate: SemanticMemoryCandidate,
        embedding: tuple[float, ...],
        embedding_model: str,
        embedding_version: str,
        projector_name: str,
        projector_version: str,
        now: datetime,
    ) -> UUID:
        live_same = await session.scalar(
            select(SemanticMemoryRow).where(
                SemanticMemoryRow.user_id == user_id,
                SemanticMemoryRow.assertion_hash == candidate.assertion_hash,
                SemanticMemoryRow.status.in_(("candidate", "active")),
            )
        )
        if live_same is not None and live_same.origin == candidate.origin.value:
            await self._add_memory_evidence(session, live_same.id, user_id, candidate, now)
            if live_same.status == SemanticMemoryStatus.CANDIDATE.value:
                groups = await self._primary_group_count(session, live_same.id)
                confidence = min(0.90, 0.40 + 0.15 * groups)
                live_same.confidence = confidence
                if confidence >= 0.70:
                    live_same.status = SemanticMemoryStatus.ACTIVE.value
                    live_same.activated_at = now
            live_same.updated_at = now
            return live_same.id

        active = await session.scalar(
            select(SemanticMemoryRow).where(
                SemanticMemoryRow.user_id == user_id,
                SemanticMemoryRow.type == candidate.type.value,
                SemanticMemoryRow.subject_key == candidate.subject_key,
                SemanticMemoryRow.status == SemanticMemoryStatus.ACTIVE.value,
            )
        )
        status = candidate.initial_status
        memory_id = new_id()
        superseded_by_id: UUID | None = None
        superseded_active: SemanticMemoryRow | None = None
        if active is not None:
            if candidate_precedes_active(candidate, _semantic_from_row(active)):
                active.status = SemanticMemoryStatus.SUPERSEDED.value
                active.superseded_by_id = None
                active.superseded_at = now
                active.updated_at = now
                # 先释放 partial unique active slot，再插入新 active revision。
                await session.flush()
                superseded_active = active
            else:
                status = SemanticMemoryStatus.SUPERSEDED
                superseded_by_id = active.id

        row = SemanticMemoryRow(
            id=memory_id,
            user_id=user_id,
            type=candidate.type.value,
            origin=candidate.origin.value,
            subject_key=candidate.subject_key,
            value=candidate.value,
            content=candidate.content,
            assertion_hash=candidate.assertion_hash,
            confidence=candidate.confidence,
            status=status.value,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            activated_at=now if status is SemanticMemoryStatus.ACTIVE else None,
            expired_at=None,
            source_occurred_at=candidate.source_occurred_at,
            projector_name=projector_name,
            projector_version=projector_version,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            embedding=list(embedding),
            superseded_by_id=superseded_by_id,
            superseded_at=now if status is SemanticMemoryStatus.SUPERSEDED else None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        if superseded_active is not None:
            superseded_active.superseded_by_id = row.id
        await self._add_memory_evidence(session, row.id, user_id, candidate, now)
        return row.id

    async def _add_memory_evidence(
        self,
        session: AsyncSession,
        memory_id: UUID,
        user_id: UUID,
        candidate: SemanticMemoryCandidate,
        now: datetime,
    ) -> None:
        existing = {
            (row.source_type, row.source_id, row.role)
            for row in (
                await session.scalars(
                    select(MemoryEvidenceRow).where(MemoryEvidenceRow.memory_id == memory_id)
                )
            ).all()
        }
        for item in candidate.evidence:
            identity = (item.source_type.value, item.source_id, item.role.value)
            if identity in existing:
                continue
            session.add(
                MemoryEvidenceRow(
                    id=new_id(),
                    user_id=user_id,
                    memory_id=memory_id,
                    source_type=item.source_type.value,
                    source_id=item.source_id,
                    source_occurred_at=item.source_occurred_at,
                    evidence_group_key=item.evidence_group_key,
                    independence_role=item.independence_role.value,
                    role=item.role.value,
                    created_at=now,
                )
            )
            existing.add(identity)
        await session.flush()

    async def _primary_group_count(self, session: AsyncSession, memory_id: UUID) -> int:
        rows = (
            await session.scalars(
                select(MemoryEvidenceRow.evidence_group_key).where(
                    MemoryEvidenceRow.memory_id == memory_id,
                    MemoryEvidenceRow.independence_role == "primary",
                )
            )
        ).all()
        return len(set(rows))

    async def apply_episode_projection(
        self,
        *,
        user_id: UUID,
        projector_name: str,
        projector_version: str,
        projection_key: str,
        input_fingerprint: str,
        input_checkpoint: dict[str, object],
        candidate: EpisodeCandidate | None,
        embedding: tuple[float, ...] | None,
        embedding_model: str,
        embedding_version: str,
        now: datetime,
    ) -> ProjectionResult:
        async with short_session(self._sessions, commit=True) as session:
            await lock_user_row(session, user_id)
            receipt = await self._get_receipt(
                session,
                user_id=user_id,
                projector_name=projector_name,
                projector_version=projector_version,
                projection_key=projection_key,
            )
            if (
                receipt is not None
                and receipt.status == "completed"
                and receipt.input_fingerprint == input_fingerprint
            ):
                return ProjectionResult(
                    projection_key=projection_key,
                    result_ids=tuple(
                        UUID(value) for value in receipt.result_summary.get("ids", [])
                    ),
                    replayed=True,
                )
            if (
                receipt is not None
                and receipt.status == "completed"
                and _source_identities(input_checkpoint)
                < _source_identities(receipt.input_checkpoint)
            ):
                return ProjectionResult(
                    projection_key=projection_key,
                    result_ids=tuple(
                        UUID(value) for value in receipt.result_summary.get("ids", [])
                    ),
                    replayed=True,
                    obsolete=True,
                )
            result_ids: list[UUID] = []
            if candidate is not None:
                if embedding is None:
                    raise ValueError("episode_embedding_required")
                row = await session.scalar(
                    select(EpisodeRow).where(
                        EpisodeRow.user_id == user_id,
                        EpisodeRow.type == candidate.type.value,
                        EpisodeRow.logical_key == candidate.logical_key,
                    )
                )
                if row is None:
                    row = EpisodeRow(
                        id=new_id(),
                        user_id=user_id,
                        type=candidate.type.value,
                        summary=candidate.summary,
                        started_at=candidate.started_at,
                        ended_at=candidate.ended_at,
                        completed_at=now if candidate.status is EpisodeStatus.COMPLETED else None,
                        superseded_at=None,
                        importance=candidate.importance,
                        status=candidate.status.value,
                        projector_name=projector_name,
                        projector_version=projector_version,
                        embedding_model=embedding_model,
                        embedding_version=embedding_version,
                        embedding=list(embedding),
                        logical_key=candidate.logical_key,
                        superseded_by_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    await session.flush()
                elif row.status != EpisodeStatus.SUPERSEDED.value:
                    row.summary = candidate.summary
                    row.started_at = min(row.started_at, candidate.started_at)
                    row.ended_at = max(row.ended_at, candidate.ended_at)
                    row.importance = candidate.importance
                    row.embedding = list(embedding)
                    row.embedding_model = embedding_model
                    row.embedding_version = embedding_version
                    row.projector_version = projector_version
                    if candidate.status is EpisodeStatus.COMPLETED:
                        row.status = EpisodeStatus.COMPLETED.value
                        row.completed_at = row.completed_at or now
                    row.updated_at = now
                await self._add_episode_evidence(session, row.id, user_id, candidate, now)
                result_ids.append(row.id)
            self._complete_receipt(
                session,
                receipt=receipt,
                user_id=user_id,
                projector_name=projector_name,
                projector_version=projector_version,
                projection_key=projection_key,
                input_fingerprint=input_fingerprint,
                input_checkpoint=input_checkpoint,
                result_ids=result_ids,
                now=now,
            )
            await session.flush()
            return ProjectionResult(projection_key, tuple(result_ids), replayed=False)

    async def _add_episode_evidence(
        self,
        session: AsyncSession,
        episode_id: UUID,
        user_id: UUID,
        candidate: EpisodeCandidate,
        now: datetime,
    ) -> None:
        existing = {
            (row.source_type, row.source_id, row.role)
            for row in (
                await session.scalars(
                    select(EpisodeEvidenceRow).where(EpisodeEvidenceRow.episode_id == episode_id)
                )
            ).all()
        }
        for item in candidate.evidence:
            identity = (item.source_type.value, item.source_id, item.role.value)
            if identity not in existing:
                session.add(
                    EpisodeEvidenceRow(
                        id=new_id(),
                        user_id=user_id,
                        episode_id=episode_id,
                        source_type=item.source_type.value,
                        source_id=item.source_id,
                        source_occurred_at=item.source_occurred_at,
                        role=item.role.value,
                        created_at=now,
                    )
                )
                existing.add(identity)

    async def _get_receipt(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        projector_name: str,
        projector_version: str,
        projection_key: str,
    ) -> MemoryProjectionRunRow | None:
        return await session.scalar(
            select(MemoryProjectionRunRow).where(
                MemoryProjectionRunRow.user_id == user_id,
                MemoryProjectionRunRow.projector_name == projector_name,
                MemoryProjectionRunRow.projector_version == projector_version,
                MemoryProjectionRunRow.projection_key == projection_key,
            )
        )

    def _complete_receipt(
        self,
        session: AsyncSession,
        *,
        receipt: MemoryProjectionRunRow | None,
        user_id: UUID,
        projector_name: str,
        projector_version: str,
        projection_key: str,
        input_fingerprint: str,
        input_checkpoint: dict[str, object],
        result_ids: list[UUID],
        now: datetime,
    ) -> None:
        summary = {"ids": [str(value) for value in result_ids]}
        if receipt is None:
            session.add(
                MemoryProjectionRunRow(
                    id=new_id(),
                    user_id=user_id,
                    projector_name=projector_name,
                    projector_version=projector_version,
                    projection_key=projection_key,
                    input_fingerprint=input_fingerprint,
                    input_checkpoint=input_checkpoint,
                    status="completed",
                    result_summary=summary,
                    error_code=None,
                    started_at=now,
                    completed_at=now,
                )
            )
        else:
            receipt.input_fingerprint = input_fingerprint
            receipt.input_checkpoint = input_checkpoint
            receipt.status = "completed"
            receipt.result_summary = summary
            receipt.error_code = None
            receipt.started_at = now
            receipt.completed_at = now

    async def has_retrievable(self, *, user_id: UUID, as_of: datetime) -> bool:
        semantic = select(SemanticMemoryRow.id).where(
            SemanticMemoryRow.user_id == user_id,
            SemanticMemoryRow.activated_at.is_not(None),
            SemanticMemoryRow.activated_at <= as_of,
            or_(SemanticMemoryRow.superseded_at.is_(None), SemanticMemoryRow.superseded_at > as_of),
            or_(SemanticMemoryRow.expired_at.is_(None), SemanticMemoryRow.expired_at > as_of),
            SemanticMemoryRow.valid_from <= as_of,
            or_(SemanticMemoryRow.valid_until.is_(None), SemanticMemoryRow.valid_until > as_of),
        )
        episode = select(EpisodeRow.id).where(
            EpisodeRow.user_id == user_id,
            EpisodeRow.completed_at.is_not(None),
            EpisodeRow.completed_at <= as_of,
            or_(EpisodeRow.superseded_at.is_(None), EpisodeRow.superseded_at > as_of),
            EpisodeRow.ended_at <= as_of,
        )
        async with short_session(self._sessions) as session:
            return (await session.scalar(semantic.limit(1))) is not None or (
                await session.scalar(episode.limit(1))
            ) is not None

    async def search_semantic(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
        query_embedding: tuple[float, ...],
        limit: int,
    ) -> tuple[RankedSemanticCandidate, ...]:
        distance = SemanticMemoryRow.embedding.cosine_distance(list(query_embedding))
        stmt = (
            select(SemanticMemoryRow, distance.label("distance"))
            .where(
                SemanticMemoryRow.user_id == user_id,
                SemanticMemoryRow.activated_at.is_not(None),
                SemanticMemoryRow.activated_at <= as_of,
                or_(
                    SemanticMemoryRow.superseded_at.is_(None),
                    SemanticMemoryRow.superseded_at > as_of,
                ),
                or_(SemanticMemoryRow.expired_at.is_(None), SemanticMemoryRow.expired_at > as_of),
                SemanticMemoryRow.valid_from <= as_of,
                or_(SemanticMemoryRow.valid_until.is_(None), SemanticMemoryRow.valid_until > as_of),
            )
            .order_by(distance.asc(), SemanticMemoryRow.id.asc())
            .limit(limit)
        )
        async with short_session(self._sessions) as session:
            rows = (await session.execute(stmt)).all()
        return tuple(
            RankedSemanticCandidate(_semantic_from_row(row), max(0.0, min(1.0, 1 - float(dist))))
            for row, dist in rows
        )

    async def search_episodes(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
        query_embedding: tuple[float, ...],
        limit: int,
    ) -> tuple[RankedEpisodeCandidate, ...]:
        distance = EpisodeRow.embedding.cosine_distance(list(query_embedding))
        stmt = (
            select(EpisodeRow, distance.label("distance"))
            .where(
                EpisodeRow.user_id == user_id,
                EpisodeRow.completed_at.is_not(None),
                EpisodeRow.completed_at <= as_of,
                or_(EpisodeRow.superseded_at.is_(None), EpisodeRow.superseded_at > as_of),
                EpisodeRow.ended_at <= as_of,
            )
            .order_by(distance.asc(), EpisodeRow.id.asc())
            .limit(limit)
        )
        async with short_session(self._sessions) as session:
            rows = (await session.execute(stmt)).all()
        return tuple(
            RankedEpisodeCandidate(_episode_from_row(row), max(0.0, min(1.0, 1 - float(dist))))
            for row, dist in rows
        )

    async def expire_due(self, *, user_id: UUID, as_of: datetime) -> int:
        stmt = (
            update(SemanticMemoryRow)
            .where(
                SemanticMemoryRow.user_id == user_id,
                SemanticMemoryRow.status == SemanticMemoryStatus.ACTIVE.value,
                SemanticMemoryRow.valid_until.is_not(None),
                SemanticMemoryRow.valid_until <= as_of,
            )
            .values(status=SemanticMemoryStatus.EXPIRED.value, expired_at=as_of, updated_at=as_of)
        )
        async with short_session(self._sessions, commit=True) as session:
            result = await session.execute(stmt)
            return int(result.rowcount or 0)


def _semantic_from_row(row: SemanticMemoryRow) -> SemanticMemory:
    value = tuple(row.value) if isinstance(row.value, list) else row.value
    return SemanticMemory(
        id=row.id,
        user_id=row.user_id,
        type=SemanticMemoryType(row.type),
        origin=MemoryOrigin(row.origin),
        subject_key=row.subject_key,
        value=value,
        content=row.content,
        assertion_hash=row.assertion_hash,
        confidence=row.confidence,
        status=SemanticMemoryStatus(row.status),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        activated_at=row.activated_at,
        expired_at=row.expired_at,
        source_occurred_at=row.source_occurred_at,
        projector_name=row.projector_name,
        projector_version=row.projector_version,
        embedding_model=row.embedding_model,
        embedding_version=row.embedding_version,
        embedding=tuple(float(item) for item in row.embedding),
        superseded_by_id=row.superseded_by_id,
        superseded_at=row.superseded_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _episode_from_row(row: EpisodeRow) -> Episode:
    return Episode(
        id=row.id,
        user_id=row.user_id,
        type=EpisodeType(row.type),
        summary=row.summary,
        started_at=row.started_at,
        ended_at=row.ended_at,
        completed_at=row.completed_at,
        superseded_at=row.superseded_at,
        importance=row.importance,
        status=EpisodeStatus(row.status),
        projector_name=row.projector_name,
        projector_version=row.projector_version,
        embedding_model=row.embedding_model,
        embedding_version=row.embedding_version,
        embedding=tuple(float(item) for item in row.embedding),
        logical_key=row.logical_key,
        superseded_by_id=row.superseded_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _source_identities(checkpoint: dict[str, object]) -> set[tuple[str, str]]:
    sources = checkpoint.get("sources")
    if not isinstance(sources, list):
        return set()
    identities: set[tuple[str, str]] = set()
    for source in sources:
        if isinstance(source, dict) and "type" in source and "id" in source:
            identities.add((str(source["type"]), str(source["id"])))
    return identities
