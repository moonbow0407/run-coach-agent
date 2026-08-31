"""两个 v1 Episode 类型的显式窗口投影。"""

from datetime import datetime
from uuid import UUID

from app.common.clock import Clock
from app.common.errors import DomainError
from app.memory.application.fingerprint import fingerprint
from app.memory.domain.episode import EpisodeType
from app.memory.domain.evidence import EvidenceSourceType
from app.memory.ports.embedding import EmbeddingProvider
from app.memory.ports.evidence_reader import EvidenceReader, ValidatedEvidence
from app.memory.ports.extractor import EpisodeDetector
from app.memory.ports.repositories import MemoryRepository, ProjectionResult

PROJECTOR_NAME = "episode"
EMBEDDING_DIMENSIONS = 1536


class EpisodeProjectionService:
    def __init__(
        self,
        *,
        evidence_reader: EvidenceReader,
        detector: EpisodeDetector,
        embedding: EmbeddingProvider,
        repository: MemoryRepository,
        clock: Clock,
    ) -> None:
        self._evidence = evidence_reader
        self._detector = detector
        self._embedding = embedding
        self._repository = repository
        self._clock = clock

    async def project_window(
        self,
        *,
        user_id: UUID,
        type: EpisodeType,
        started_at: datetime,
        ended_at: datetime,
        source_ids: tuple[tuple[EvidenceSourceType, UUID], ...],
        projector_version: str,
    ) -> ProjectionResult:
        sources = await self._evidence.read_many(user_id=user_id, source_ids=source_ids)
        if any(
            source.source_occurred_at < started_at or source.source_occurred_at > ended_at
            for source in sources
        ):
            raise DomainError("episode_evidence_outside_window")
        projection_key = _episode_anchor(type, sources)
        candidate = await self._detector.detect(
            type=type,
            started_at=started_at,
            ended_at=ended_at,
            evidence=sources,
        )
        if candidate is not None and candidate.logical_key != projection_key:
            raise DomainError("episode_detector_changed_logical_identity")
        checkpoint = {
            "sources": [
                {
                    "type": item.source_type.value,
                    "id": str(item.source_id),
                    "version": item.source_version,
                }
                for item in sorted(
                    sources, key=lambda source: (source.source_type.value, str(source.source_id))
                )
            ]
        }
        vector: tuple[float, ...] | None = None
        model = "none"
        version = "none"
        if candidate is not None:
            batch = await self._embedding.embed((candidate.summary,))
            if (
                batch.dimensions != EMBEDDING_DIMENSIONS
                or len(batch.vectors) != 1
                or len(batch.vectors[0]) != EMBEDDING_DIMENSIONS
            ):
                raise DomainError("memory_embedding_contract_mismatch")
            vector = batch.vectors[0]
            model = batch.model
            version = batch.version
        return await self._repository.apply_episode_projection(
            user_id=user_id,
            projector_name=PROJECTOR_NAME,
            projector_version=projector_version,
            projection_key=projection_key,
            input_fingerprint=fingerprint(checkpoint),
            input_checkpoint=checkpoint,
            candidate=candidate,
            embedding=vector,
            embedding_model=model,
            embedding_version=version,
            now=self._clock.now(),
        )


def _episode_anchor(type: EpisodeType, sources: tuple[ValidatedEvidence, ...]) -> str:
    if type is EpisodeType.PLAN_ADAPTATION_OUTCOME:
        source = next(
            (item for item in sources if item.source_type is EvidenceSourceType.PLAN_CHANGE), None
        )
        if source is None:
            raise DomainError("plan_episode_requires_plan_change_anchor")
        return f"plan_change:{source.source_id}"
    snapshots = sorted(
        (item for item in sources if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT),
        key=lambda item: (item.source_occurred_at, str(item.source_id)),
    )
    if not snapshots:
        raise DomainError("fatigue_episode_requires_snapshot_anchor")
    return f"fatigue_trigger:{snapshots[0].source_id}"
