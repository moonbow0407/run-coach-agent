"""SafetyGate：在 ToolExecutor 执行 DRAFT/MUTATING 前应用 CoachingSafetyPolicy。"""

from uuid import UUID

from app.tools.registry.definition import ToolDefinition, ToolRisk
from app.tools.safety.evidence import SafetyEvidenceSource
from app.tools.safety.policy import CoachingSafetyPolicy, SafetyDecision, SafetyStatus


class SafetyGate:
    """取证 + 策略判定的统一入口；Executor 与 get_safety_status 共用。"""

    def __init__(
        self,
        *,
        evidence: SafetyEvidenceSource,
        policy: CoachingSafetyPolicy | None = None,
    ) -> None:
        self._evidence = evidence
        self._policy = policy or CoachingSafetyPolicy()

    async def status_for(self, *, user_id: UUID) -> SafetyStatus:
        """计算当前用户的安全约束快照。"""
        snapshot = await self._evidence.latest_athlete_state(user_id=user_id)
        notes = await self._evidence.recent_feedback_notes(user_id=user_id)
        return self._policy.evaluate_status(
            fatigue_level=snapshot.fatigue_level if snapshot else None,
            recovery_level=snapshot.recovery_level if snapshot else None,
            feedback_notes=notes,
        )

    async def check(
        self,
        *,
        user_id: UUID,
        definition: ToolDefinition,
    ) -> SafetyDecision:
        """对即将执行的工具做放行判定；非 DRAFT/MUTATING 时仍返回 status 但直接放行。"""
        status = await self.status_for(user_id=user_id)
        return self._policy.decide(
            tool_name=definition.name,
            risk=definition.risk,
            tags=definition.tags,
            status=status,
        )

    def requires_check(self, risk: ToolRisk) -> bool:
        """是否需要在执行前走安全闸门。"""
        return risk in {ToolRisk.DRAFT, ToolRisk.MUTATING}
