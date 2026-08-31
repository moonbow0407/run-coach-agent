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
    def __init__(
        self,
        *,
        terminal_turn_finalization: TerminalTurnFinalizationService,
        athlete_recompute: AthleteStateRecomputeService,
        semantic_projection: SemanticMemoryProjectionService,
        episode_projection: EpisodeProjectionService,
        memory_projector_version: str,
    ) -> None:
        self._terminal_turn_finalization = terminal_turn_finalization
        self._athlete_recompute = athlete_recompute
        self._semantic_projection = semantic_projection
        self._episode_projection = episode_projection
        self._memory_projector_version = memory_projector_version

    def mapping(self) -> dict[str, TaskHandler]:
        return {
            FINALIZE_TERMINAL_TURN: self.finalize_terminal_turn,
            RECOMPUTE_ATHLETE_STATE: self.recompute_athlete_state,
            PROJECT_SEMANTIC_MEMORY: self.project_semantic_memory,
            PROJECT_EPISODE: self.project_episode,
        }

    async def finalize_terminal_turn(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        event = task.event
        if event.event_type == TURN_COMMITTED_V1:
            payload = decode_turn_committed(event)
            await self._terminal_turn_finalization.finalize(
                user_id=event.user_id,
                turn_id=payload.turn_id,
                terminal_status=TurnStatus.COMMITTED,
            )
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
            raise DomainError("unsupported_terminal_turn_event")
        return TaskOutcome.SUCCESS

    async def recompute_athlete_state(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        event = task.event
        if event.event_type == WORKOUT_CHANGED_V1:
            payload = decode_workout_changed(event)
            trigger = AthleteStateTrigger(
                source_type=AthleteStateTriggerType.WORKOUT,
                source_id=payload.workout_id,
                available_at=payload.available_at,
            )
        elif event.event_type == WORKOUT_FEEDBACK_CHANGED_V1:
            payload = decode_workout_feedback_changed(event)
            trigger = AthleteStateTrigger(
                source_type=AthleteStateTriggerType.WORKOUT_FEEDBACK,
                source_id=payload.feedback_id,
                workout_id=payload.workout_id,
                available_at=payload.available_at,
            )
        else:
            raise DomainError("unsupported_athlete_recompute_event")
        result = await self._athlete_recompute.recompute_for_trigger(
            user_id=event.user_id,
            trigger=trigger,
            trigger_available_at=trigger.available_at,
            event_metadata=_caused_by(task),
        )
        return TaskOutcome.SUCCESS if result.appended else TaskOutcome.OBSOLETE_NOOP

    async def project_semantic_memory(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        event = task.event
        payload = decode_turn_committed(event)
        result = await self._semantic_projection.project_committed_turn(
            user_id=event.user_id,
            turn_id=payload.turn_id,
            projector_version=self._memory_projector_version,
        )
        return _projection_outcome(result.replayed, result.obsolete)

    async def project_episode(self, task: WorkerTaskEnvelope) -> TaskOutcome:
        event = task.event
        if event.event_type == ATHLETE_STATE_RECOMPUTED_V1:
            payload = decode_athlete_state_recomputed(event)
            trigger_type = EvidenceSourceType.ATHLETE_STATE_SNAPSHOT
            trigger_id = payload.snapshot_id
        elif event.event_type == PLAN_CHANGE_CONFIRMED_V1:
            payload = decode_plan_change_confirmed(event)
            trigger_type = EvidenceSourceType.PLAN_CHANGE
            trigger_id = payload.plan_change_id
        else:
            raise DomainError("unsupported_episode_projection_event")
        results = await self._episode_projection.project_trigger(
            user_id=event.user_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            projector_version=self._memory_projector_version,
        )
        if not results or all(result.replayed or result.obsolete for result in results):
            return TaskOutcome.OBSOLETE_NOOP
        return TaskOutcome.SUCCESS


def _caused_by(task: WorkerTaskEnvelope) -> EventMetadata:
    event = task.event
    return EventMetadata(
        correlation_id=event.metadata.correlation_id,
        causation_id=event.event_id,
        trace_id=event.metadata.trace_id,
    )


def _projection_outcome(replayed: bool, obsolete: bool) -> TaskOutcome:
    return TaskOutcome.OBSOLETE_NOOP if replayed or obsolete else TaskOutcome.SUCCESS
