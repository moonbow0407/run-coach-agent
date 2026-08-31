"""Phase 4 两类 Episode 的保守确定性 Detector。

Detector 只使用经 EvidenceReader 筛选的少量 canonical 字段；没有恢复结果时
保持 BUILDING，不把“之后可能有效”写成已发生结果。
"""

from datetime import datetime

from app.memory.domain.episode import (
    EpisodeCandidate,
    EpisodeEvidenceRef,
    EpisodeEvidenceRole,
    EpisodeType,
)
from app.memory.domain.evidence import EvidenceSourceType
from app.memory.ports.evidence_reader import ValidatedEvidence


class CanonicalEpisodeDetector:
    async def detect(
        self,
        *,
        type: EpisodeType,
        started_at: datetime,
        ended_at: datetime,
        evidence: tuple[ValidatedEvidence, ...],
    ) -> EpisodeCandidate | None:
        if type is EpisodeType.PLAN_ADAPTATION_OUTCOME:
            return _plan_adaptation(started_at, ended_at, evidence)
        return _fatigue_and_recovery(started_at, ended_at, evidence)


def _plan_adaptation(
    started_at: datetime,
    ended_at: datetime,
    evidence: tuple[ValidatedEvidence, ...],
) -> EpisodeCandidate | None:
    plan_change = next(
        (item for item in evidence if item.source_type is EvidenceSourceType.PLAN_CHANGE),
        None,
    )
    if plan_change is None:
        return None
    trigger = _latest_before(
        evidence,
        plan_change.source_occurred_at,
        allowed=(EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, EvidenceSourceType.WORKOUT_FEEDBACK),
    )
    if trigger is None:
        return None
    outcome = _recovery_after(evidence, plan_change.source_occurred_at)
    refs = [
        _episode_ref(trigger, EpisodeEvidenceRole.TRIGGER),
        _episode_ref(plan_change, EpisodeEvidenceRole.INTERVENTION),
    ]
    if outcome is not None:
        refs.append(_episode_ref(outcome, EpisodeEvidenceRole.OUTCOME))
        summary = (
            f"{started_at.date()} 至 {ended_at.date()}：基于跑者状态确认了训练计划调整，"
            "后续状态证据显示疲劳降低或恢复改善。"
        )
    else:
        summary = (
            f"{started_at.date()} 至 {ended_at.date()}：已确认训练计划调整，"
            "目前尚无足够的后续恢复证据。"
        )
    return EpisodeCandidate(
        type=EpisodeType.PLAN_ADAPTATION_OUTCOME,
        summary=summary,
        started_at=started_at,
        ended_at=ended_at,
        importance=0.75,
        logical_key=f"plan_change:{plan_change.source_id}",
        evidence=tuple(refs),
    )


def _fatigue_and_recovery(
    started_at: datetime,
    ended_at: datetime,
    evidence: tuple[ValidatedEvidence, ...],
) -> EpisodeCandidate | None:
    trigger = next(
        (
            item
            for item in sorted(evidence, key=lambda source: source.source_occurred_at)
            if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
            and item.facts.get("fatigue_level") in {"high", "moderate"}
        ),
        None,
    )
    if trigger is None:
        return None
    intervention = next(
        (
            item
            for item in evidence
            if item.source_type is EvidenceSourceType.PLAN_CHANGE
            and item.source_occurred_at >= trigger.source_occurred_at
        ),
        None,
    )
    outcome = _recovery_after(evidence, trigger.source_occurred_at)
    refs = [_episode_ref(trigger, EpisodeEvidenceRole.TRIGGER)]
    if intervention is not None:
        refs.append(_episode_ref(intervention, EpisodeEvidenceRole.INTERVENTION))
    if outcome is not None:
        refs.append(_episode_ref(outcome, EpisodeEvidenceRole.OUTCOME))
        summary = (
            f"{started_at.date()} 至 {ended_at.date()}：出现疲劳积累，"
            "后续正式状态证据显示疲劳降低或恢复改善。"
        )
    else:
        summary = (
            f"{started_at.date()} 至 {ended_at.date()}：出现疲劳积累，目前尚未观察到完整恢复结果。"
        )
    return EpisodeCandidate(
        type=EpisodeType.FATIGUE_AND_RECOVERY,
        summary=summary,
        started_at=started_at,
        ended_at=ended_at,
        importance=0.85,
        logical_key=f"fatigue_trigger:{trigger.source_id}",
        evidence=tuple(refs),
    )


def _latest_before(
    evidence: tuple[ValidatedEvidence, ...],
    cutoff: datetime,
    *,
    allowed: tuple[EvidenceSourceType, ...],
) -> ValidatedEvidence | None:
    candidates = [
        item
        for item in evidence
        if item.source_type in allowed and item.source_occurred_at <= cutoff
    ]
    return max(candidates, key=lambda item: item.source_occurred_at, default=None)


def _recovery_after(
    evidence: tuple[ValidatedEvidence, ...], cutoff: datetime
) -> ValidatedEvidence | None:
    candidates = [
        item
        for item in evidence
        if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
        and item.source_occurred_at > cutoff
        and (item.facts.get("fatigue_level") == "low" or item.facts.get("recovery_level") == "good")
    ]
    return min(candidates, key=lambda item: item.source_occurred_at, default=None)


def _episode_ref(source: ValidatedEvidence, role: EpisodeEvidenceRole) -> EpisodeEvidenceRef:
    return EpisodeEvidenceRef(
        source_type=source.source_type,
        source_id=source.source_id,
        source_occurred_at=source.source_occurred_at,
        role=role,
    )
