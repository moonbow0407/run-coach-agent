"""用户锁覆盖完整证据读取与提交的 Athlete State 重算入口。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.coaching.application.training_analysis_service import (
    analyze_training_load_evidence,
)
from app.coaching.domain.athlete.evaluator import (
    AthleteStateEvaluatorV1,
    AthleteStateEvidence,
)
from app.coaching.domain.athlete.models import AthleteStateSnapshot
from app.coaching.ports.athlete_recompute_uow import (
    AthleteStateRecomputeUnitOfWork,
    AthleteStateTrigger,
)
from app.common.clock import Clock
from app.common.errors import DomainError
from app.common.events import EventMetadata
from app.common.ids import new_id


@dataclass(frozen=True)
class AthleteStateRecomputeResult:
    """一次重算的结果：新追加的快照，或命中幂等时返回的既有快照。"""

    snapshot: AthleteStateSnapshot  # 本次生效的状态快照（新追加或既有）
    appended: bool  # False 表示证据未变化，直接复用了最新快照


class AthleteStateRecomputeService:
    """跑者状态重算应用服务：在用户锁事务内读证据、评估、追加快照。"""

    def __init__(
        self,
        *,
        unit_of_work: AthleteStateRecomputeUnitOfWork,
        clock: Clock,
        evaluator: AthleteStateEvaluatorV1 | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        # 默认使用 phase3.v1 评估器，测试可注入替身。
        self._evaluator = evaluator or AthleteStateEvaluatorV1()

    async def recompute(
        self,
        *,
        user_id: UUID,
        as_of: datetime | None = None,
        event_metadata: EventMetadata | None = None,
    ) -> AthleteStateSnapshot:
        """显式重算入口；内部命令未提供关联 ID 时创建新的可信 correlation。"""
        result = await self.recompute_for_trigger(
            user_id=user_id,
            trigger=None,
            trigger_available_at=as_of if as_of is not None else self._clock.now(),
            event_metadata=(
                event_metadata or EventMetadata(correlation_id=new_id())
            ),
        )
        return result.snapshot

    async def recompute_for_trigger(
        self,
        *,
        user_id: UUID,
        trigger: AthleteStateTrigger | None,
        trigger_available_at: datetime,
        event_metadata: EventMetadata,
    ) -> AthleteStateRecomputeResult:
        # 业务时间必须带时区，否则跨时区的证据窗口切分会有歧义。
        if trigger_available_at.tzinfo is None:
            raise DomainError("athlete_state_trigger_requires_timezone")
        # 进入用户锁事务：同一用户的证据读取与快照写入在锁内原子完成。
        async with self._unit_of_work.transaction(user_id=user_id) as transaction:
            evidence = await transaction.load_evidence(
                trigger=trigger,
                trigger_available_at=trigger_available_at,
                observed_at=max(self._clock.now(), trigger_available_at),
            )
            latest = evidence.latest_snapshot
            # 幂等短路：证据截止线未越过最新快照且算法版本一致，说明没有新事实。
            if (
                latest is not None
                and evidence.cutoff <= latest.as_of
                and latest.algorithm_version == self._evaluator.algorithm_version
            ):
                return AthleteStateRecomputeResult(snapshot=latest, appended=False)

            # 投影时间取证据截止线与最新快照的较晚者，保证快照时间单调前进。
            projection_as_of = (
                max(evidence.cutoff, latest.as_of)
                if latest is not None
                else evidence.cutoff
            )
            # 先做确定性负荷分析，再交给评估器得出疲劳 / 恢复结论。
            analysis = analyze_training_load_evidence(
                as_of=projection_as_of,
                workouts=evidence.workouts,
                feedback=evidence.feedback,
            )
            assessment = self._evaluator.evaluate(
                AthleteStateEvidence(
                    as_of=projection_as_of,
                    recent_workouts=evidence.workouts,
                    recent_feedback=evidence.feedback,
                    training_load_analysis=analysis,
                )
            )
            # 只追加新版快照，不覆盖历史判断。
            snapshot = await transaction.append_snapshot(
                as_of=projection_as_of,
                assessment=assessment,
                created_at=self._clock.now(),
                event_metadata=event_metadata,
            )
            return AthleteStateRecomputeResult(snapshot=snapshot, appended=True)
