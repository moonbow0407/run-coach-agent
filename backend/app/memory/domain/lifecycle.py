"""Semantic Memory 生命周期的纯领域判断。"""

from datetime import datetime

from app.memory.domain.semantic import MemoryOrigin, SemanticMemory, SemanticMemoryCandidate


def candidate_precedes_active(candidate: SemanticMemoryCandidate, active: SemanticMemory) -> bool:
    """按事实发生时间判定候选是否足以替代当前认知，而非按投影执行顺序。"""
    if candidate.source_occurred_at < active.source_occurred_at:
        return False
    if candidate.origin is MemoryOrigin.INFERRED and active.origin is MemoryOrigin.EXPLICIT:
        return False
    return not (
        candidate.origin is MemoryOrigin.INFERRED and candidate.confidence <= active.confidence
    )


def is_retrievable_at(memory: SemanticMemory, as_of: datetime) -> bool:
    return (
        memory.activated_at is not None
        and memory.activated_at <= as_of
        and (memory.superseded_at is None or memory.superseded_at > as_of)
        and (memory.expired_at is None or memory.expired_at > as_of)
        and memory.valid_from <= as_of
        and (memory.valid_until is None or memory.valid_until > as_of)
    )
