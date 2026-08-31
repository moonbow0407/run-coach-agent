"""Semantic Memory 投影：外部模型调用与短持久化事务严格分离。"""

import hashlib
from uuid import UUID

from app.agent.ports.conversation_reader import ConversationReader
from app.common.clock import Clock
from app.common.errors import DomainError, NotFoundError
from app.memory.application.fingerprint import fingerprint
from app.memory.domain.evidence import EvidenceRef, EvidenceSourceType
from app.memory.domain.semantic import MemoryOrigin, SemanticMemoryCandidate, SemanticMemoryType
from app.memory.ports.embedding import EmbeddingProvider
from app.memory.ports.evidence_reader import EvidenceReader, ValidatedEvidence
from app.memory.ports.extractor import ExtractedSemanticCandidate, SemanticMemoryExtractor
from app.memory.ports.repositories import MemoryRepository, ProjectionResult

PROJECTOR_NAME = "semantic_memory"
EMBEDDING_DIMENSIONS = 1536


class SemanticMemoryProjectionService:
    def __init__(
        self,
        *,
        conversations: ConversationReader,
        evidence_reader: EvidenceReader,
        extractor: SemanticMemoryExtractor,
        embedding: EmbeddingProvider,
        repository: MemoryRepository,
        clock: Clock,
    ) -> None:
        self._conversations = conversations
        self._evidence = evidence_reader
        self._extractor = extractor
        self._embedding = embedding
        self._repository = repository
        self._clock = clock

    async def project_committed_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        projector_version: str,
    ) -> ProjectionResult:
        committed = await self._conversations.get_committed_turn_messages(
            user_id=user_id, turn_id=turn_id
        )
        if committed is None:
            raise NotFoundError("committed_turn_not_found")
        extracted = await self._extractor.extract(
            user_message=committed.user_message,
            assistant_message=committed.assistant_message,
            committed_at=committed.committed_at,
            supported_types=tuple(SemanticMemoryType),
        )
        group_key = f"conversation:turn:{turn_id}"
        candidates: list[SemanticMemoryCandidate] = []
        for item in extracted:
            if item.origin is not MemoryOrigin.EXPLICIT:
                raise DomainError("conversation_projection_requires_explicit_candidate")
            candidates.append(
                SemanticMemoryCandidate(
                    type=item.type,
                    origin=item.origin,
                    subject_key=item.subject_key,
                    value=item.value,
                    content=item.content,
                    valid_from=item.valid_from,
                    valid_until=item.valid_until,
                    evidence=(
                        EvidenceRef(
                            source_type=EvidenceSourceType.MESSAGE,
                            source_id=committed.user_message.id,
                            source_occurred_at=committed.user_message.created_at,
                            evidence_group_key=group_key,
                            independence_role=_primary(),
                        ),
                        EvidenceRef(
                            source_type=EvidenceSourceType.TURN,
                            source_id=turn_id,
                            source_occurred_at=committed.committed_at,
                            evidence_group_key=group_key,
                            independence_role=_derived(),
                        ),
                    ),
                )
            )
        checkpoint = {
            "turn_id": str(turn_id),
            "user_message_id": str(committed.user_message.id),
            "assistant_message_id": str(committed.assistant_message.id),
            "committed_at": committed.committed_at.isoformat(),
            "user_content_hash": hashlib.sha256(
                committed.user_message.content.encode("utf-8")
            ).hexdigest(),
            "assistant_content_hash": hashlib.sha256(
                committed.assistant_message.content.encode("utf-8")
            ).hexdigest(),
        }
        batch = await self._embed(tuple(item.content for item in candidates))
        return await self._repository.apply_semantic_projection(
            user_id=user_id,
            projector_name=PROJECTOR_NAME,
            projector_version=projector_version,
            projection_key=f"turn:{turn_id}",
            input_fingerprint=fingerprint(checkpoint),
            input_checkpoint=checkpoint,
            candidates=tuple(candidates),
            embeddings=batch.vectors,
            embedding_model=batch.model,
            embedding_version=batch.version,
            now=self._clock.now(),
        )

    async def project_evidence_set(
        self,
        *,
        user_id: UUID,
        candidate: ExtractedSemanticCandidate,
        source_ids: tuple[tuple[EvidenceSourceType, UUID], ...],
        projector_version: str,
    ) -> ProjectionResult:
        if candidate.origin is not MemoryOrigin.INFERRED:
            raise DomainError("evidence_set_projection_requires_inferred_candidate")
        sources = await self._evidence.read_many(user_id=user_id, source_ids=source_ids)
        evidence = tuple(_memory_evidence(item) for item in sources)
        semantic = SemanticMemoryCandidate(
            type=candidate.type,
            origin=candidate.origin,
            subject_key=candidate.subject_key,
            value=candidate.value,
            content=candidate.content,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            evidence=evidence,
        )
        checkpoint = _source_checkpoint(sources)
        identity = fingerprint({"sources": sorted(str(item) for item in source_ids)})
        batch = await self._embed((semantic.content,))
        return await self._repository.apply_semantic_projection(
            user_id=user_id,
            projector_name=PROJECTOR_NAME,
            projector_version=projector_version,
            projection_key=f"inferred:{candidate.type.value}:{identity}",
            input_fingerprint=fingerprint(checkpoint),
            input_checkpoint=checkpoint,
            candidates=(semantic,),
            embeddings=batch.vectors,
            embedding_model=batch.model,
            embedding_version=batch.version,
            now=self._clock.now(),
        )

    async def _embed(self, texts: tuple[str, ...]):
        if not texts:
            from app.memory.ports.embedding import EmbeddingBatch

            return EmbeddingBatch((), "none", "none", EMBEDDING_DIMENSIONS)
        batch = await self._embedding.embed(texts)
        if batch.dimensions != EMBEDDING_DIMENSIONS or len(batch.vectors) != len(texts):
            raise DomainError("memory_embedding_contract_mismatch")
        if any(len(vector) != EMBEDDING_DIMENSIONS for vector in batch.vectors):
            raise DomainError("memory_embedding_dimension_mismatch")
        return batch


def _source_checkpoint(sources: tuple[ValidatedEvidence, ...]) -> dict[str, object]:
    return {
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


def _memory_evidence(source: ValidatedEvidence) -> EvidenceRef:
    return EvidenceRef(
        source_type=source.source_type,
        source_id=source.source_id,
        source_occurred_at=source.source_occurred_at,
        evidence_group_key=source.evidence_group_key,
        independence_role=source.independence_role,
    )


def _primary():
    from app.memory.domain.evidence import EvidenceIndependenceRole

    return EvidenceIndependenceRole.PRIMARY


def _derived():
    from app.memory.domain.evidence import EvidenceIndependenceRole

    return EvidenceIndependenceRole.DERIVED_CONTEXT
