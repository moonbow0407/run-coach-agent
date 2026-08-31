from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.memory.domain.evidence import (
    EvidenceIndependenceRole,
    EvidenceRef,
    EvidenceSourceType,
)
from app.memory.domain.lifecycle import candidate_precedes_active
from app.memory.domain.semantic import (
    MemoryOrigin,
    SemanticMemory,
    SemanticMemoryCandidate,
    SemanticMemoryStatus,
    SemanticMemoryType,
)

NOW = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)


def test_assertion_hash_is_normalized_and_origin_independent() -> None:
    explicit = _candidate(
        origin=MemoryOrigin.EXPLICIT,
        value="  Evening   RUN ",
        evidence=(_evidence("conversation:turn:1"),),
    )
    inferred = _candidate(
        origin=MemoryOrigin.INFERRED,
        value="evening run",
        evidence=(_evidence("training:workout:1"),),
    )

    assert explicit.assertion_hash == inferred.assertion_hash
    assert explicit.confidence == 1.0
    assert explicit.initial_status is SemanticMemoryStatus.ACTIVE


def test_inferred_promotion_counts_distinct_primary_groups() -> None:
    one_experience = _candidate(
        origin=MemoryOrigin.INFERRED,
        value="slow",
        evidence=(
            _evidence("training:workout:1", EvidenceSourceType.WORKOUT),
            _evidence("training:workout:1", EvidenceSourceType.WORKOUT_FEEDBACK),
        ),
    )
    two_experiences = _candidate(
        origin=MemoryOrigin.INFERRED,
        value="slow",
        evidence=one_experience.evidence
        + (_evidence("training:workout:2", EvidenceSourceType.WORKOUT),),
    )

    assert one_experience.confidence == 0.55
    assert one_experience.initial_status is SemanticMemoryStatus.CANDIDATE
    assert two_experiences.confidence == 0.70
    assert two_experiences.initial_status is SemanticMemoryStatus.ACTIVE


def test_event_time_and_explicit_priority_control_supersession() -> None:
    active = _memory(origin=MemoryOrigin.EXPLICIT, source_occurred_at=NOW)
    older_explicit = _candidate(
        origin=MemoryOrigin.EXPLICIT,
        value="morning",
        evidence=(_evidence("conversation:turn:old", at=NOW - timedelta(days=1)),),
    )
    newer_inferred = _candidate(
        origin=MemoryOrigin.INFERRED,
        value="morning",
        evidence=(
            _evidence("training:workout:1", at=NOW + timedelta(days=1)),
            _evidence("training:workout:2", at=NOW + timedelta(days=2)),
        ),
    )
    newer_explicit = _candidate(
        origin=MemoryOrigin.EXPLICIT,
        value="morning",
        evidence=(_evidence("conversation:turn:new", at=NOW + timedelta(days=1)),),
    )

    assert not candidate_precedes_active(older_explicit, active)
    assert not candidate_precedes_active(newer_inferred, active)
    assert candidate_precedes_active(newer_explicit, active)


def _candidate(
    *,
    origin: MemoryOrigin,
    value: str,
    evidence: tuple[EvidenceRef, ...],
) -> SemanticMemoryCandidate:
    return SemanticMemoryCandidate(
        type=SemanticMemoryType.SCHEDULE_PREFERENCE,
        origin=origin,
        subject_key="preferred_training_time",
        value=value,
        content="用户偏好在该时段训练",
        valid_from=min(item.source_occurred_at for item in evidence),
        valid_until=None,
        evidence=evidence,
    )


def _evidence(
    group: str,
    source_type: EvidenceSourceType = EvidenceSourceType.MESSAGE,
    *,
    at: datetime = NOW,
) -> EvidenceRef:
    return EvidenceRef(
        source_type=source_type,
        source_id=uuid4(),
        source_occurred_at=at,
        evidence_group_key=group,
        independence_role=EvidenceIndependenceRole.PRIMARY,
    )


def _memory(*, origin: MemoryOrigin, source_occurred_at: datetime) -> SemanticMemory:
    return SemanticMemory(
        id=uuid4(),
        user_id=uuid4(),
        type=SemanticMemoryType.SCHEDULE_PREFERENCE,
        origin=origin,
        subject_key="preferred_training_time",
        value="evening",
        content="用户偏好晚上训练",
        assertion_hash="a" * 64,
        confidence=1.0,
        status=SemanticMemoryStatus.ACTIVE,
        valid_from=source_occurred_at,
        valid_until=None,
        activated_at=source_occurred_at,
        expired_at=None,
        source_occurred_at=source_occurred_at,
        projector_name="semantic_memory",
        projector_version="phase4.v1",
        embedding_model="fake",
        embedding_version="1",
        embedding=(1.0,),
        superseded_by_id=None,
        superseded_at=None,
        created_at=source_occurred_at,
        updated_at=source_occurred_at,
    )
