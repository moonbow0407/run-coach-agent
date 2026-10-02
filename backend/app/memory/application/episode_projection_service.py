"""两个 v1 Episode 类型的显式窗口与 durable trigger 投影。

把已确认的证据（状态快照、计划变更等）投影为疲劳恢复或计划调整
两类情景记忆（Episode），并生成检索用向量。
"""

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

PROJECTOR_NAME = "episode"  # 投影器名：仓储端按它区分不同投影器的输出
EMBEDDING_DIMENSIONS = 1536  # 向量维度契约：嵌入结果必须严格一致
EPISODE_WINDOW = timedelta(days=28)  # 触发点前后的证据搜索窗口长度
# 参与 Episode 证据筛选的来源白名单（仅这三类来源可构成情景记忆）
_EPISODE_SOURCE_TYPES = (
    EvidenceSourceType.WORKOUT_FEEDBACK,
    EvidenceSourceType.ATHLETE_STATE_SNAPSHOT,
    EvidenceSourceType.PLAN_CHANGE,
)


class EpisodeProjectionService:
    """Episode 投影服务：从 durable trigger 出发，重评疲劳/计划两类情景记忆。"""

    def __init__(
        self,
        *,
        evidence_reader: EvidenceReader,
        detector: EpisodeDetector,
        embedding: EmbeddingProvider,
        repository: MemoryRepository,
        clock: Clock,
    ) -> None:
        # 依赖全部是端口抽象，便于替换实现与测试注入。
        self._evidence = evidence_reader  # 证据读取端口：只读已确认来源
        self._detector = detector  # Episode 检测端口：外部模型生成摘要候选
        self._embedding = embedding  # 向量化端口：摘要转为检索向量
        self._repository = repository  # Memory 仓储端口：短事务原子合并
        self._clock = clock  # 时钟端口：统一"当前时间"基准

    async def project_trigger(
        self,
        *,
        user_id: UUID,
        trigger_type: EvidenceSourceType,
        trigger_id: UUID,
        projector_version: str,
    ) -> tuple[ProjectionResult, ...]:
        """根据 durable trigger 选择有界 canonical evidence 并重评相关 Episode。"""
        # 只有状态快照与计划变更可作为 durable trigger 触发重评。
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
        # 搜索窗口：向前 28 天取历史证据；向后最多 28 天且不超过当前时间，
        # 避免把"未来"的证据提前纳入本次重评。
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
        # 疲劳恢复窗口：以触发点前最近一段"中/高疲劳"证据为锚点。
        fatigue_sources = _fatigue_episode_sources(
            candidates,
            cutoff=trigger.source_occurred_at,
        )
        if fatigue_sources:
            windows.append((EpisodeType.FATIGUE_AND_RECOVERY, fatigue_sources))

        # 计划调整窗口：计划变更触发时以它为锚点，否则取触发点之前的计划变更。
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
        # 同一（类型, 锚点来源）只投影一次，防止重复窗口重复落库。
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
        """挑选计划调整 Episode 的证据：依据的状态快照、计划变更与首次恢复。"""
        based_on_state = plan_change.facts.get("based_on_state_id")
        if not isinstance(based_on_state, str):
            raise DomainError("plan_change_missing_state_evidence")
        # 计划变更必须回指一份状态快照，否则无法解释"基于什么状态做的调整"。
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
        # 候选窗口里没有该快照时回源补读，保证证据链完整。
        if state is None:
            state = (
                await self._evidence.read_many(
                    user_id=user_id,
                    source_ids=((EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, state_id),),
                )
            )[0]
        # 状态快照必须发生在计划变更之前（先有状态，后基于它做调整）。
        if state.source_occurred_at > plan_change.source_occurred_at:
            raise DomainError("plan_change_state_evidence_after_confirmation")
        # 计划变更之后的首次恢复快照作为结果证据（可能尚不存在）。
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
        """把显式证据窗口投影为一个 Episode：检测、校验、向量化后交仓储幂等合并。"""
        sources = await self._evidence.read_many(user_id=user_id, source_ids=source_ids)
        # 全部证据都必须落在声明的窗口内，防止窗口边界被悄悄放大。
        if any(
            source.source_occurred_at < started_at or source.source_occurred_at > ended_at
            for source in sources
        ):
            raise DomainError("episode_evidence_outside_window")
        projection_key = _episode_anchor(type, sources)
        # 检测器认定的逻辑身份必须与投影键一致，避免同一窗口出现两个身份。
        candidate = await self._detector.detect(
            type=type,
            started_at=started_at,
            ended_at=ended_at,
            evidence=sources,
        )
        if candidate is not None and candidate.logical_key != projection_key:
            raise DomainError("episode_detector_changed_logical_identity")
        # 检查点只记录证据的 identity/version（排序后），用于幂等重放判断。
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
        # 无成形候选时不产生 Episode 内容，只把窗口合并为空结果；有候选才向量化。
        vector: tuple[float, ...] | None = None
        model = "none"
        version = "none"
        if candidate is not None:
            batch = await self._embedding.embed((candidate.summary,))
            # 嵌入供应商返回的维度与数量必须严格符合契约。
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
    """把触发源并入候选集合并按发生时间排序，保证窗口内顺序确定。"""
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
    """选出疲劳 Episode 证据：锚点=最后一次恢复之后的首个中/高疲劳快照。"""
    states = [
        item
        for item in candidates
        if item.source_type is EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
        and item.source_occurred_at <= cutoff
    ]
    # cutoff 之前最近一次"恢复良好"的时间点：只统计其后的疲劳风险。
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
    # 没有疲劳风险快照就不构成疲劳 Episode。
    if not risks:
        return ()
    anchor = min(risks, key=_evidence_order)
    # 锚点之后如果发生过计划变更，视为干预证据。
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
    # 锚点之后的首次恢复作为结果证据（可能尚未出现）。
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
    """取 cutoff 之后首次"恢复良好"的状态快照，作为 Episode 的结果证据。"""
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
    """状态快照是否代表已恢复：疲劳低或恢复好，任一成立即可。"""
    return (
        source.facts.get("fatigue_level") == "low"
        or source.facts.get("recovery_level") == "good"
    )


def _evidence_order(source: ValidatedEvidence) -> tuple[datetime, int, str]:
    """证据排序键：发生时间 → 快照版本 → ID，保证同刻证据顺序确定。"""
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
    """窗口锚点证据：计划类取计划变更，疲劳类取最早的中/高疲劳快照。"""
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
    """投影键：由锚点来源唯一标识窗口，同键重复投影可幂等合并。"""
    source = _anchor_source(type, sources)
    if type is EpisodeType.PLAN_ADAPTATION_OUTCOME:
        return f"plan_change:{source.source_id}"
    return f"fatigue_trigger:{source.source_id}"