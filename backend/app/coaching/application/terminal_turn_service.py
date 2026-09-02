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
        """校验 durable event 与 canonical Turn 一致后，执行计划草案收尾。"""
        # 事件声称的 Turn 在 canonical 读取侧不存在：数据不一致，拒绝投影。
        turn = await self._conversations.get_turn(user_id=user_id, turn_id=turn_id)
        if turn is None:
            raise NotFoundError("canonical_turn_source_not_found")
        # 事件携带的终态与 canonical Turn 实际状态不一致，同样拒绝投影。
        if turn.status is not terminal_status:
            raise DomainError("canonical_turn_status_mismatch")
        # Turn 提交成功：草案推进到待确认；Turn 失败 / 中止：草案直接作废。
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
