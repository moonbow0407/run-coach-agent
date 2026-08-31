"""终态 Turn durable event 的 canonical source 校验与计划草案收尾。"""

from uuid import UUID

from app.agent.models.turn import TurnStatus
from app.agent.ports.conversation_reader import ConversationReader
from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.common.errors import DomainError, NotFoundError


class TerminalTurnFinalizationService:
    """只有 canonical Turn 的 owner 与终态完全匹配时才执行投影。"""

    def __init__(
        self,
        *,
        conversations: ConversationReader,
        plan_adaptation: PlanAdaptationService,
    ) -> None:
        self._conversations = conversations
        self._plan_adaptation = plan_adaptation

    async def finalize(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        terminal_status: TurnStatus,
    ) -> None:
        turn = await self._conversations.get_turn(user_id=user_id, turn_id=turn_id)
        if turn is None:
            raise NotFoundError("canonical_turn_source_not_found")
        if turn.status is not terminal_status:
            raise DomainError("canonical_turn_status_mismatch")
        if terminal_status is TurnStatus.COMMITTED:
            await self._plan_adaptation.promote_draft_for_turn(
                user_id=user_id,
                turn_id=turn_id,
            )
        else:
            await self._plan_adaptation.abandon_draft_for_turn(
                user_id=user_id,
                turn_id=turn_id,
            )
