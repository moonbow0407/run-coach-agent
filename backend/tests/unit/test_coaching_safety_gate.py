"""CoachingSafetyPolicy / SafetyGate 的允许与拒绝用例（假取证，无 IO）。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agent.models.action import ToolCallAction
from app.coaching.domain.athlete.models import (
    ALGORITHM_VERSION_V1,
    AthleteStateSnapshot,
    FatigueLevel,
    RecoveryLevel,
)
from app.tools.context import ToolExecutionContext
from app.tools.executor.errors import ToolErrorCode
from app.tools.executor.executor import ToolExecutor
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource
from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.resolver import ToolResolver
from app.tools.resolver.session import ToolSession
from app.tools.safety.constants import (
    FLAG_HIGH_FATIGUE_POOR_RECOVERY,
    FLAG_INJURY_KEYWORDS,
    REASON_FATIGUE_BLOCKS_NON_REDUCE,
    REASON_INCREASE_LOAD_FORBIDDEN,
    REASON_INJURY_BLOCKS_NON_REST,
)
from app.tools.safety.gate import SafetyGate
from app.tools.safety.policy import CoachingSafetyPolicy
from app.tools.search.keyword_search import KeywordToolSearch
from tests.unit.tool_helpers import SampleArgs, SampleTool


@dataclass
class _FakeEvidence:
    """单元测试用假取证：直接注入状态与备注。"""

    snapshot: AthleteStateSnapshot | None
    notes: list[str]

    async def latest_athlete_state(self, *, user_id):
        return self.snapshot

    async def recent_feedback_notes(self, *, user_id):
        return list(self.notes)


def _snapshot(
    *,
    fatigue: FatigueLevel | None,
    recovery: RecoveryLevel | None,
) -> AthleteStateSnapshot:
    now = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)
    return AthleteStateSnapshot(
        id=uuid4(),
        user_id=uuid4(),
        version=1,
        as_of=now,
        fatigue_level=fatigue,
        recovery_level=recovery,
        recent_training_load=None,
        workout_completion_rate=None,
        training_load_coverage=None,
        signals=(),
        confidence=0.8,
        algorithm_version=ALGORITHM_VERSION_V1,
        created_at=now,
    )


def _ctx() -> ToolExecutionContext:
    uid = uuid4()
    return ToolExecutionContext(
        user_id=uid,
        thread_id=uuid4(),
        turn_id=uuid4(),
        run_id=uuid4(),
        call_id=uuid4(),
        request_id=uuid4(),
        trace_id=uuid4(),
        timestamp=datetime(2026, 9, 5, 2, 0, tzinfo=UTC),
    )


class _DraftProbeTool:
    """可配置名称 / tags 的 DRAFT 探测工具。"""

    def __init__(self, name: str, *, tags: tuple[str, ...] = ("probe",)) -> None:
        self._name = name
        self._tags = tags

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=f"{self._name} draft probe",
            tags=self._tags,
            search_hint=self._name,
            always_on=True,
            risk=ToolRisk.DRAFT,
            source=ToolSource.COACHING,
            timeout_s=1.0,
        )

    @property
    def args_model(self) -> type[SampleArgs]:
        return SampleArgs

    async def execute(self, *, args: SampleArgs, context: ToolExecutionContext) -> object:
        return {"ok": True, "value": args.value}


def test_policy_flags_high_fatigue_poor_recovery() -> None:
    status = CoachingSafetyPolicy().evaluate_status(
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.POOR,
        feedback_notes=[],
    )
    assert status.ok is False
    assert FLAG_HIGH_FATIGUE_POOR_RECOVERY in status.flags
    assert status.reasons


def test_policy_flags_injury_keywords_zh_en() -> None:
    status = CoachingSafetyPolicy().evaluate_status(
        fatigue_level=FatigueLevel.LOW,
        recovery_level=RecoveryLevel.GOOD,
        feedback_notes=["膝盖很疼", "mild Knee swelling after long run"],
    )
    assert status.ok is False
    assert FLAG_INJURY_KEYWORDS in status.flags
    # 中英关键词都应命中
    joined = " ".join(status.reasons)
    assert "疼" in joined or "伤痛" in joined


def test_policy_allows_reduce_under_fatigue() -> None:
    policy = CoachingSafetyPolicy()
    status = policy.evaluate_status(
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.POOR,
        feedback_notes=[],
    )
    decision = policy.decide(
        tool_name="propose_plan_adaptation",
        risk=ToolRisk.DRAFT,
        tags=("adaptation", "reduce_load"),
        status=status,
    )
    assert decision.allowed is True


def test_policy_allows_convert_easy_under_fatigue() -> None:
    policy = CoachingSafetyPolicy()
    status = policy.evaluate_status(
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.POOR,
        feedback_notes=[],
    )
    decision = policy.decide(
        tool_name="propose_convert_hard_sessions_to_easy",
        risk=ToolRisk.DRAFT,
        tags=("adaptation", "convert_easy"),
        status=status,
    )
    assert decision.allowed is True


def test_policy_blocks_unknown_draft_under_fatigue() -> None:
    policy = CoachingSafetyPolicy()
    status = policy.evaluate_status(
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.POOR,
        feedback_notes=[],
    )
    decision = policy.decide(
        tool_name="propose_increase_volume",
        risk=ToolRisk.DRAFT,
        tags=("adaptation",),
        status=status,
    )
    assert decision.allowed is False
    assert decision.reason_code == REASON_FATIGUE_BLOCKS_NON_REDUCE


def test_policy_injury_allows_only_reduce_rest() -> None:
    policy = CoachingSafetyPolicy()
    status = policy.evaluate_status(
        fatigue_level=FatigueLevel.MODERATE,
        recovery_level=RecoveryLevel.FAIR,
        feedback_notes=["右膝肿了，injury after tempo"],
    )
    assert FLAG_INJURY_KEYWORDS in status.flags

    allow = policy.decide(
        tool_name="propose_plan_adaptation",
        risk=ToolRisk.DRAFT,
        tags=("adaptation", "reduce_load"),
        status=status,
    )
    deny = policy.decide(
        tool_name="propose_convert_hard_sessions_to_easy",
        risk=ToolRisk.DRAFT,
        tags=("adaptation", "convert_easy"),
        status=status,
    )
    assert allow.allowed is True
    assert deny.allowed is False
    assert deny.reason_code == REASON_INJURY_BLOCKS_NON_REST


def test_policy_blocks_increase_load_tag_when_constrained() -> None:
    policy = CoachingSafetyPolicy()
    status = policy.evaluate_status(
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.POOR,
        feedback_notes=[],
    )
    decision = policy.decide(
        tool_name="propose_add_intervals",
        risk=ToolRisk.DRAFT,
        tags=("adaptation", "increase_load"),
        status=status,
    )
    assert decision.allowed is False
    assert decision.reason_code == REASON_INCREASE_LOAD_FORBIDDEN


def test_policy_read_only_always_allowed() -> None:
    policy = CoachingSafetyPolicy()
    status = policy.evaluate_status(
        fatigue_level=FatigueLevel.HIGH,
        recovery_level=RecoveryLevel.POOR,
        feedback_notes=["knee pain"],
    )
    decision = policy.decide(
        tool_name="get_latest_athlete_state",
        risk=ToolRisk.READ_ONLY,
        tags=("athlete",),
        status=status,
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_executor_returns_safety_blocked_for_denied_draft() -> None:
    """Executor 集成：伤痛备注下转轻松跑草案返回 safety_blocked。"""
    evidence = _FakeEvidence(
        snapshot=_snapshot(fatigue=FatigueLevel.MODERATE, recovery=RecoveryLevel.FAIR),
        notes=["跑后膝盖很痛"],
    )
    gate = SafetyGate(evidence=evidence)
    registry = ToolRegistry(search=KeywordToolSearch())
    tool = _DraftProbeTool("propose_convert_hard_sessions_to_easy")
    registry.register(tool)
    resolver = ToolResolver(registry=registry)
    executor = ToolExecutor(registry=registry, resolver=resolver, safety_gate=gate)

    context = _ctx()
    session = ToolSession(run_id=context.run_id, registry=registry)
    observation = await executor.execute(
        action=ToolCallAction(
            tool="propose_convert_hard_sessions_to_easy",
            arguments={"value": 1},
            model_call_id="call-safety-1",
        ),
        session=session,
        context=context,
    )
    assert observation.status == "error"
    assert observation.error_code == ToolErrorCode.SAFETY_BLOCKED.value
    assert REASON_INJURY_BLOCKS_NON_REST in (observation.error or "")


@pytest.mark.asyncio
async def test_executor_allows_reduce_under_injury() -> None:
    evidence = _FakeEvidence(
        snapshot=_snapshot(fatigue=None, recovery=None),
        notes=["ankle sprain"],
    )
    gate = SafetyGate(evidence=evidence)
    registry = ToolRegistry(search=KeywordToolSearch())
    registry.register(_DraftProbeTool("propose_plan_adaptation", tags=("reduce_load",)))
    resolver = ToolResolver(registry=registry)
    executor = ToolExecutor(registry=registry, resolver=resolver, safety_gate=gate)

    context = _ctx()
    session = ToolSession(run_id=context.run_id, registry=registry)
    observation = await executor.execute(
        action=ToolCallAction(
            tool="propose_plan_adaptation",
            arguments={"value": 2},
            model_call_id="call-safety-2",
        ),
        session=session,
        context=context,
    )
    assert observation.status == "success"
    assert observation.data == {"ok": True, "value": 2}


@pytest.mark.asyncio
async def test_executor_skips_gate_for_read_only() -> None:
    """只读工具不走安全闸门，即使状态极差也直接执行。"""
    evidence = _FakeEvidence(
        snapshot=_snapshot(fatigue=FatigueLevel.HIGH, recovery=RecoveryLevel.POOR),
        notes=["injury"],
    )
    gate = SafetyGate(evidence=evidence)
    registry = ToolRegistry(search=KeywordToolSearch())
    registry.register(SampleTool("get_recent_workouts", always_on=True))
    resolver = ToolResolver(registry=registry)
    executor = ToolExecutor(registry=registry, resolver=resolver, safety_gate=gate)

    context = _ctx()
    session = ToolSession(run_id=context.run_id, registry=registry)
    observation = await executor.execute(
        action=ToolCallAction(
            tool="get_recent_workouts",
            arguments={"value": 3},
            model_call_id="call-safety-3",
        ),
        session=session,
        context=context,
    )
    assert observation.status == "success"


@pytest.mark.asyncio
async def test_gate_status_for_ok_when_unconstrained() -> None:
    gate = SafetyGate(
        evidence=_FakeEvidence(
            snapshot=_snapshot(fatigue=FatigueLevel.LOW, recovery=RecoveryLevel.GOOD),
            notes=["感觉不错"],
        )
    )
    status = await gate.status_for(user_id=uuid4())
    assert status.ok is True
    assert status.flags == ()
