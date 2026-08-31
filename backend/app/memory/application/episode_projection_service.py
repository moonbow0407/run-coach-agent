"""两个 v1 Episode 类型的显式窗口与 durable trigger 投影。"""

from datetime import datetime, timedelta
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
EPISODE_WINDOW = timedelta(days=28)
_EPISODE_SOURCE_TYPES = (
    EvidenceSourceType.WORKOUT_FEEDBACK,
    EvidenceSourceType.ATHLETE_STATE_SNAPSHOT,
    EvidenceSourceType.PLAN_CHANGE,
)


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

    async def project_trigger(
        self,
        *,
        user_id: UUID,
        trigger_type: EvidenceSourceType,
        trigger_id: UUID,
        projector_version: str,
    ) -> tuple[ProjectionResult, ...]:
        """根据 durable trigger 选择有界 canonical evidence 并重评相关 Episode。"""
        if trigger_type not in {
            EvidenceSourceType.ATHLETE_STATE_SNAPSHOT,
            EvidenceSourceType.PLAN_CHANGE,
        }:
            raise DomainError("unsupported_episode_trigger")
        trigger_sources = await self._evidence.read_many(
            user_id=user_id,
            source_ids=((trigger_type, trigger_id),),
        )
        trigger = trigger_sources[0]
        search_start = trigger.source_occurred_at - EPISODE_WINDOW
        search_end = max(
            trigger.source_occurred_at,
            min(trigger.source_occurred_at + EPISODE_WINDOW, self._clock.now()),
        )
        candidates = await self._evidence.read_window(
            user_id=user_id,
            started_at=search_start,
            ended_at=search_end,
            source_types=_EPISODE_SOURCE_TYPES,
        )
        candidates = _include_trigger(candidates, trigger)

        windows: list[tuple[EpisodeType, tuple[ValidatedEvidence, ...]]] = []
        fatigue_sources = _fatigue_episode_sources(
            candidates,
            cutoff=trigger.source_occurred_at,
        )
        if fatigue_sources:
            windows.append((EpisodeType.FATIGUE_AND_RECOVERY, fatigue_sources))

        plan_anchors = (
            (trigger,)
            if trigger_type is EvidenceSourceType.PLAN_CHANGE
            else tuple(
                item
                for item in candidates
                if item.source_type is EvidenceSourceType.PLAN_CHANGE
                and item.source_occurred_at <= trigger.source_occurred_at
            )
        )
        for plan_change in plan_anchors:
            plan_sources = await self._plan_episode_sources(
                user_id=user_id,
                plan_change=plan_change,
                candidates=candidates,
            )
            if plan_sources:
                windows.append((EpisodeType.PLAN_ADAPTATION_OUTCOME, plan_sources))

        results: list[ProjectionResult] = []
        seen: set[tuple[EpisodeType, UUID]] = set()
        for type, sources in windows:
            anchor = _anchor_source(type, sources)
            identity = (type, anchor.source_id)
            if identity in seen:
                continue
            seen.add(identity)
            results.append(
                await self.project_window(
                    user_id=user_id,
                    type=type,
                    started_at=min(item.source_occurred_at for item in sources),
                    ended_at=max(item.source_occurred_at for item in sources),
                    source_ids=tuple((item.source_type, item.source_id) for item in sources),
                    projector_version=projector_version,
                )
            )
        return tuple(results)

    async def _plan_episode_sources(
        self,
        *,
        user_id: UUID,
        plan_change: ValidatedEvidence,
        candidates: tuple[ValidatedEvidence, ...],
    ) -> tuple[ValidatedEvidence, ...]:
        based_on_state = plan_change.facts.get("based_on_state_id")
        if not isinstance(based_on_state, str):
            raise DomainError("plan_change_missing_state_evidence")
        try:
            state_id = UUID(based_on_state)
        except ValueError as exc:
            raise DomainError("plan_change_invalid_state_evidence") from exc
        state = next(
            (
                item
                for item in candidates
                if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
                and item.source_id == state_id
            ),
            None,
        )
        if state is None:
            state = (
                await self._evidence.read_many(
                    user_id=user_id,
                    source_ids=((EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, state_id),),
                )
            )[0]
        if state.source_occurred_at > plan_change.source_occurred_at:
            raise DomainError("plan_change_state_evidence_after_confirmation")
        outcome = _first_recovery_after(candidates, plan_change.source_occurred_at)
        selected = [state, plan_change]
        if outcome is not None:
            selected.append(outcome)
        return tuple(selected)

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


def _include_trigger(
    candidates: tuple[ValidatedEvidence, ...],
    trigger: ValidatedEvidence,
) -> tuple[ValidatedEvidence, ...]:
    by_identity = {(item.source_type, item.source_id): item for item in candidates}
    by_identity[(trigger.source_type, trigger.source_id)] = trigger
    return tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (
                item.source_occurred_at,
                item.source_type.value,
                str(item.source_id),
            ),
        )
    )


def _fatigue_episode_sources(
    candidates: tuple[ValidatedEvidence, ...],
    *,
    cutoff: datetime,
) -> tuple[ValidatedEvidence, ...]:
    states = [
        item
        for item in candidates
        if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
        and item.source_occurred_at <= cutoff
    ]
    last_recovery_at = max(
        (
            item.source_occurred_at
            for item in states
            if _is_recovery(item) and item.source_occurred_at < cutoff
        ),
        default=None,
    )
    risks = [
        item
        for item in states
        if item.facts.get("fatigue_level") in {"high", "moderate"}
        and (last_recovery_at is None or item.source_occurred_at > last_recovery_at)
    ]
    if not risks:
        return ()
    anchor = min(risks, key=_evidence_order)
    plan_change = min(
        (
            item
            for item in candidates
            if item.source_type is EvidenceSourceType.PLAN_CHANGE
            and item.source_occurred_at >= anchor.source_occurred_at
        ),
        key=_evidence_order,
        default=None,
    )
    outcome = _first_recovery_after(candidates, anchor.source_occurred_at)
    selected = [anchor]
    if plan_change is not None:
        selected.append(plan_change)
    if outcome is not None:
        selected.append(outcome)
    return tuple(selected)


def _first_recovery_after(
    candidates: tuple[ValidatedEvidence, ...],
    cutoff: datetime,
) -> ValidatedEvidence | None:
    return min(
        (
            item
            for item in candidates
            if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
            and item.source_occurred_at > cutoff
            and _is_recovery(item)
        ),
        key=_evidence_order,
        default=None,
    )


def _is_recovery(source: ValidatedEvidence) -> bool:
    return (
        source.facts.get("fatigue_level") == "low"
        or source.facts.get("recovery_level") == "good"
    )


def _evidence_order(source: ValidatedEvidence) -> tuple[datetime, int, str]:
    version = source.facts.get("snapshot_version")
    return (
        source.source_occurred_at,
        version if isinstance(version, int) else 0,
        str(source.source_id),
    )


def _anchor_source(
    type: EpisodeType,
    sources: tuple[ValidatedEvidence, ...],
) -> ValidatedEvidence:
    if type is EpisodeType.PLAN_ADAPTATION_OUTCOME:
        return next(item for item in sources if item.source_type is EvidenceSourceType.PLAN_CHANGE)
    return min(
        (
            item
            for item in sources
            if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
            and item.facts.get("fatigue_level") in {"high", "moderate"}
        ),
        key=_evidence_order,
    )


def _episode_anchor(type: EpisodeType, sources: tuple[ValidatedEvidence, ...]) -> str:
    source = _anchor_source(type, sources)
    if type is EpisodeType.PLAN_ADAPTATION_OUTCOME:
        return f"plan_change:{source.source_id}"
    return f"fatigue_trigger:{source.source_id}"