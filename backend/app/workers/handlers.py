"""四个 v1 durable task handler；这里只解码事件并调用正式 Application Service。"""

from app.agent.contracts.durable_events import (
    TURN_CANCELLED_V1,
    TURN_COMMITTED_V1,
    TURN_FAILED_V1,
    decode_turn_committed,
    decode_turn_terminal,
)
from app.agent.models.turn import TurnStatus
from app.coaching.application.athlete_recompute_service import (
    AthleteStateRecomputeService,
)
from app.coaching.application.terminal_turn_service import TerminalTurnFinalizationService
from app.coaching.contracts.durable_events import (
    ATHLETE_STATE_RECOMPUTED_V1,
    PLAN_CHANGE_CONFIRMED_V1,
    WORKOUT_CHANGED_V1,
    WORKOUT_FEEDBACK_CHANGED_V1,
    decode_athlete_state_recomputed,
    decode_plan_change_confirmed,
    decode_workout_changed,
    decode_workout_feedback_changed,
)
from app.coaching.ports.athlete_recompute_uow import (
    AthleteStateTrigger,
    AthleteStateTriggerType,
)
from app.common.errors import DomainError
from app.common.events import EventMetadata
from app.memory.application.episode_projection_service import EpisodeProjectionService
from app.memory.application.semantic_projection_service import (
    SemanticMemoryProjectionService,
)
from app.memory.domain.evidence import EvidenceSourceType
from app.workers.consumer import TaskHandler, TaskOutcome
from app.workers.contracts import WorkerTaskEnvelope
from app.workers.routing import (
    FINALIZE_TERMINAL_TURN,
    PROJECT_EPISODE,
    PROJECT_SEMANTIC_MEMORY,
    RECOMPUTE_ATHLETE_STATE,
)


class DurableTaskHandlers:
    """四类 durable task 的处理器集合：只做事件解码与分发，业务规则都在 Application Service。"""

    def __init__(
        self,
        *,
        terminal_turn_finalization: TerminalTurnFinalizationService,
        athlete_recompute: AthleteStateRecomputeService,
        semantic_projection: SemanticMemoryProjectionService,
        episode_projection: EpisodeProjectionService,
        memory_projector_version: str,
    ) -> None:
        self._terminal_turn_finalization = terminal_turn_finalization  # Turn（一轮对话）终态收尾服务
        self._athlete_recompute = athlete_recompute  # 跑者状态重算服务
        self._semantic_projection = semantic_projection  # 语义记忆投影服务
        self._episode_projection = episode_projection  # 情节记忆投影服务
        self._memory_projector_version = memory_projector_version  # 投影器版本号：随结果落库，便于重建追溯

    def mapping(self) -> dict[str, TaskHandler]:
        """任务名 → 处理器注册表，消费者据此分发任务。"""
        return {
            FINALIZE_TERMINAL_TURN: self.finalize_terminal_turn,
            RECOMPUTE_ATHLETE_STATE: self.recompute_athlete_state,
            PROJECT_SEMANTIC_MEMORY: self.project_semantic_memory,
            PROJECT_EPISODE: self.project_episode,
        }

    async def finalize_terminal_turn(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        """Turn 终态收尾：提交 / 失败 / 取消三类事件都汇入同一个收尾服务。"""
        event = task.event
        # 正常提交的 Turn。
        if event.event_type == TURN_COMMITTED_V1:
            payload = decode_turn_committed(event)
            await self._terminal_turn_finalization.finalize(
                user_id=event.user_id,
                turn_id=payload.turn_id,
                terminal_status=TurnStatus.COMMITTED,
            )
        # 失败或被取消的 Turn：同样要推进到终态。
        elif event.event_type in {TURN_FAILED_V1, TURN_CANCELLED_V1}:
            payload = decode_turn_terminal(event)
            await self._terminal_turn_finalization.finalize(
                user_id=event.user_id,
                turn_id=payload.turn_id,
                terminal_status=(
                    TurnStatus.FAILED
                    if event.event_type == TURN_FAILED_V1
                    else TurnStatus.CANCELLED
                ),
            )
        else:
            # 其余事件类型说明契约被破坏：按领域错误处理（永久失败）。
            raise DomainError("unsupported_terminal_turn_event")
        return TaskOutcome.SUCCESS

    async def recompute_athlete_state(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        """按训练课 / 反馈变更事件重算跑者状态快照。"""
        event = task.event
        # 训练课变更触发。
        if event.event_type == WORKOUT_CHANGED_V1:
            payload = decode_workout_changed(event)
            trigger = AthleteStateTrigger(
                source_type=AthleteStateTriggerType.WORKOUT,
                source_id=payload.workout_id,
                available_at=payload.available_at,
            )
        # 主观反馈变更触发（携带关联的训练课 ID）。
        elif event.event_type == WORKOUT_FEEDBACK_CHANGED_V1:
            payload = decode_workout_feedback_changed(event)
            trigger = AthleteStateTrigger(
                source_type=AthleteStateTriggerType.WORKOUT_FEEDBACK,
                source_id=payload.feedback_id,
                workout_id=payload.workout_id,
                available_at=payload.available_at,
            )
        else:
            # 未支持的事件类型：契约破坏，永久失败。
            raise DomainError("unsupported_athlete_recompute_event")
        result = await self._athlete_recompute.recompute_for_trigger(
            user_id=event.user_id,
            trigger=trigger,
            trigger_available_at=trigger.available_at,
            event_metadata=_caused_by(task),
        )
        # 没有追加新快照说明该事件已被后续事件覆盖，按过时跳过。
        return TaskOutcome.SUCCESS if result.appended else TaskOutcome.OBSOLETE_NOOP

    async def project_semantic_memory(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        """把已提交的 Turn 投影为语义记忆（长期事实记忆）。"""
        event = task.event
        payload = decode_turn_committed(event)
        result = await self._semantic_projection.project_committed_turn(
            user_id=event.user_id,
            turn_id=payload.turn_id,
            projector_version=self._memory_projector_version,
        )
        return _projection_outcome(result.replayed, result.obsolete)

    async def project_episode(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        """把状态快照 / 计划确认事件投影为情节记忆（带证据的记忆条目）。"""
        event = task.event
        # 证据源：跑者状态快照。
        if event.event_type == ATHLETE_STATE_RECOMPUTED_V1:
            payload = decode_athlete_state_recomputed(event)
            trigger_type = EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
            trigger_id = payload.snapshot_id
        # 证据源：计划调整确认。
        elif event.event_type == PLAN_CHANGE_CONFIRMED_V1:
            payload = decode_plan_change_confirmed(event)
            trigger_type = EvidenceSourceType.PLAN_CHANGE
            trigger_id = payload.plan_change_id
        else:
            # 未支持的事件类型：契约破坏，永久失败。
            raise DomainError("unsupported_episode_projection_event")
        results = await self._episode_projection.project_trigger(
            user_id=event.user_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            projector_version=self._memory_projector_version,
        )
        # 没有产出新条目（全部已重放或过时）：按幂等跳过处理。
        if not results or all(result.replayed or result.obsolete for result in results):
            return TaskOutcome.OBSOLETE_NOOP
        return TaskOutcome.SUCCESS


def _caused_by(task: WorkerTaskEnvelope) -> EventMetadata:
    """构造下游事件元数据：延续链路追踪 ID，causation_id 指向触发本任务的事件。"""
    event = task.event
    return EventMetadata(
        correlation_id=event.metadata.correlation_id,
        causation_id=event.event_id,
        trace_id=event.metadata.trace_id,
    )


def _projection_outcome(replayed: bool, obsolete: bool) -> TaskOutcome:
    """投影结果 → 任务结论：重放或过时都视为幂等跳过。"""
    return TaskOutcome.OBSOLETE_NOOP if replayed or obsolete else TaskOutcome.SUCCESS
