"""Semantic Memory 生命周期的纯领域判断。"""

from datetime import datetime

from app.memory.domain.semantic import MemoryOrigin, SemanticMemory, SemanticMemoryCandidate


def candidate_precedes_active(candidate: SemanticMemoryCandidate, active: SemanticMemory) -> bool:
    """按事实发生时间判定候选是否足以替代当前认知，而非按投影执行顺序。"""
    # 候选事实发生得更早：没有资格替代当前认知。
    if candidate.source_occurred_at < active.source_occurred_at:
        return False
    # 推断记忆永远不能替代用户明示的记忆。
    if candidate.origin is MemoryOrigin.INFERRED and active.origin is MemoryOrigin.EXPLICIT:
        return False
    # 同为推断时，置信度不超过现有记忆也不替代。
    return not (
        candidate.origin is MemoryOrigin.INFERRED and candidate.confidence <= active.confidence
    )


def is_retrievable_at(memory: SemanticMemory, as_of: datetime) -> bool:
    """记忆在 as_of 时刻是否可检索：已激活、未被取代/过期且在业务有效期内。"""
    # 同时满足两条时间线：生命周期（激活/取代/过期）与业务有效期。
    return (
        memory.activated_at is not None
        and memory.activated_at <= as_of
        and (memory.superseded_at is None or memory.superseded_at > as_of)
        and (memory.expired_at is None or memory.expired_at > as_of)
        and memory.valid_from <= as_of
        and (memory.valid_until is None or memory.valid_until > as_of)
    )
