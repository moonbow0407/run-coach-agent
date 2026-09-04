"""确定性 Grader 的 focused tests（PHASE 6 §23.1）。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agent.models.run import AgentRunStatus, RunStepKind
from app.coaching.domain.plan.models import PlanChangeStatus
from app.evals.errors import EvalConfigError
from app.evals.graders import (
    grade_coaching_decision,
    grade_context_injection,
    grade_memory_conflict,
    grade_tool_expectation,
)
from app.evals.models import (
    CoachingExpectation,
    ContextInjectionExpectation,
    MemoryConflictExpectation,
    ToolExpectation,
)
from app.evals.trace import EvalTrace
from app.infrastructure.evals.readers import (
    ActivePlanState,
    PlanChangeState,
    SemanticMemoryState,
)
from tests.unit.test_eval_trace import _step, _tool_run


def _trace_of(steps) -> EvalTrace:
    """给轨迹补一条 FINAL 步骤，满足 completed run 必须有 final 的不变量。"""
    last_index = max(step.index for step in steps)
    steps = [
        *steps,
        _step(index=last_index + 1, kind=RunStepKind.FINAL, output_data={"content": "done"}),
    ]
    return EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)


def test_required_tool_success_vs_attempt_only() -> None:
    """required tool 必须存在成功 Observation；仅 tool_call 不算成功。"""
    steps = _tool_run(tool="get_recent_workouts", model_call_id="m1", status="error", error_code="tool_timeout")
    trace = _trace_of(steps)
    results = grade_tool_expectation(
        ToolExpectation(required_successful_tools=["get_recent_workouts"]), trace
    )
    required = next(item for item in results if item.grader == "tool_required_success")
    assert not required.passed
    assert required.reason_code == "required_tool_not_successful"

    ok_steps = _tool_run(tool="get_recent_workouts", model_call_id="m2")
    ok_trace = _trace_of(ok_steps)
    results = grade_tool_expectation(
        ToolExpectation(required_successful_tools=["get_recent_workouts"]), ok_trace
    )
    assert next(item for item in results if item.grader == "tool_required_success").passed


def test_forbidden_tool_attempt_fails_even_when_runtime_rejects() -> None:
    """forbidden 工具只要出现 tool_call 即失败，即使执行被拒绝。"""
    steps = _tool_run(
        tool="propose_plan_adaptation",
        model_call_id="m1",
        status="error",
        error_code="tool_not_available",
    )
    trace = _trace_of(steps)
    results = grade_tool_expectation(
        ToolExpectation(forbidden_tool_attempts=["propose_plan_adaptation"]), trace
    )
    forbidden = next(item for item in results if item.grader == "tool_forbidden_attempt")
    assert not forbidden.passed
    assert forbidden.reason_code == "forbidden_tool_attempted"


def test_discovery_requires_search_hit_then_success() -> None:
    """Discovery 必须同时证明 search 命中与目标之后执行成功。"""
    # 命中但未执行 → 失败。
    steps = _tool_run(
        tool="search_tools",
        model_call_id="m1",
        data={"hits": [{"name": "get_workout_detail"}]},
    )
    results = grade_tool_expectation(
        ToolExpectation(required_discoveries=["get_workout_detail"]), _trace_of(steps)
    )
    discovery = next(item for item in results if item.grader == "tool_discovery")
    assert not discovery.passed
    assert discovery.reason_code == "discovered_tool_not_executed_successfully"

    # 命中且执行成功 → 通过。
    steps = [
        *_tool_run(
            tool="search_tools",
            model_call_id="m1",
            data={"hits": [{"name": "get_workout_detail"}]},
        ),
        *_tool_run(tool="get_workout_detail", model_call_id="m2", start_index=3),
    ]
    results = grade_tool_expectation(
        ToolExpectation(required_discoveries=["get_workout_detail"]), _trace_of(steps)
    )
    assert next(item for item in results if item.grader == "tool_discovery").passed

    # search 未命中 → 失败。
    steps = [
        *_tool_run(tool="search_tools", model_call_id="m1", data={"hits": []}),
        *_tool_run(tool="get_workout_detail", model_call_id="m2", start_index=3),
    ]
    results = grade_tool_expectation(
        ToolExpectation(required_discoveries=["get_workout_detail"]), _trace_of(steps)
    )
    discovery = next(item for item in results if item.grader == "tool_discovery")
    assert not discovery.passed
    assert discovery.reason_code == "discovery_search_missed_target"


def test_max_tool_attempts_counts_all_calls() -> None:
    """步数上限统计全部 tool_call（含 search 与失败尝试）。"""
    steps = [
        *_tool_run(tool="search_tools", model_call_id="m1", data={"hits": []}),
        *_tool_run(
            tool="get_recent_workouts",
            model_call_id="m2",
            status="error",
            error_code="tool_timeout",
            start_index=3,
        ),
    ]
    results = grade_tool_expectation(ToolExpectation(max_tool_attempts=1), _trace_of(steps))
    budget = next(item for item in results if item.grader == "tool_attempt_budget")
    assert not budget.passed
    assert budget.details["attempts"] == 2


def test_coaching_positive_requires_source_identity_and_pending() -> None:
    """正例：只接受当前 source turn/run 的 pending 提案。"""
    turn_id = uuid4()
    run_id = uuid4()
    plan_id = uuid4()
    snapshot_state_id = uuid4()
    change = PlanChangeState(
        id=uuid4(),
        from_plan_id=plan_id,
        from_plan_version=1,
        based_on_state_id=snapshot_state_id,
        based_on_state_version=1,
        source_turn_id=turn_id,
        source_run_id=run_id,
        status=PlanChangeStatus.PENDING_CONFIRMATION,
        reason="疲劳高，未来有节奏课",
    )
    other_turn_change = PlanChangeState(
        id=uuid4(),
        from_plan_id=plan_id,
        from_plan_version=1,
        based_on_state_id=snapshot_state_id,
        based_on_state_version=1,
        source_turn_id=uuid4(),  # 其他 Turn 产生的提案
        source_run_id=uuid4(),
        status=PlanChangeStatus.PENDING_CONFIRMATION,
        reason="别的轮次",
    )
    active = ActivePlanState(plan_id=plan_id, version=1, status="active")

    results = grade_coaching_decision(
        CoachingExpectation(must_create_plan_change=True),
        plan_changes=(other_turn_change,),
        active_plan=active,
        fixture_plan_id=plan_id,
        fixture_plan_version=1,
        fixture_state_version=1,
        turn_id=turn_id,
        run_id=run_id,
    )
    created = next(item for item in results if item.grader == "coaching_plan_change_created")
    assert not created.passed  # 其他 Turn 的提案不算本 Case 的结果

    results = grade_coaching_decision(
        CoachingExpectation(must_create_plan_change=True),
        plan_changes=(change,),
        active_plan=active,
        fixture_plan_id=plan_id,
        fixture_plan_version=1,
        fixture_state_version=1,
        turn_id=turn_id,
        run_id=run_id,
    )
    assert all(item.passed for item in results)


def test_coaching_negative_rejects_creation_and_plan_change() -> None:
    """负例：当前 turn/run 创建提案即失败；Active Plan 变更也失败。"""
    turn_id = uuid4()
    run_id = uuid4()
    plan_id = uuid4()
    results = grade_coaching_decision(
        CoachingExpectation(must_create_plan_change=False),
        plan_changes=(),
        active_plan=ActivePlanState(plan_id=plan_id, version=1, status="active"),
        fixture_plan_id=plan_id,
        fixture_plan_version=1,
        fixture_state_version=1,
        turn_id=turn_id,
        run_id=run_id,
    )
    assert all(item.passed for item in results)

    created = PlanChangeState(
        id=uuid4(),
        from_plan_id=plan_id,
        from_plan_version=1,
        based_on_state_id=uuid4(),
        based_on_state_version=1,
        source_turn_id=turn_id,
        source_run_id=run_id,
        status=PlanChangeStatus.DRAFT,
        reason="不该创建",
    )
    results = grade_coaching_decision(
        CoachingExpectation(must_create_plan_change=False),
        plan_changes=(created,),
        active_plan=ActivePlanState(plan_id=plan_id, version=1, status="active"),
        fixture_plan_id=plan_id,
        fixture_plan_version=1,
        fixture_state_version=1,
        turn_id=turn_id,
        run_id=run_id,
    )
    negative = next(item for item in results if item.grader == "coaching_no_plan_change")
    assert not negative.passed


def test_memory_conflict_grader_checks_lifecycle_and_new_thread_recall() -> None:
    """冲突 Grader：旧 superseded / 新 active / 链接正确 / 新 Thread 只召新知识。"""
    old_id = uuid4()
    new_id = uuid4()
    memories = (
        SemanticMemoryState(
            id=old_id,
            subject_key="preferred_training_time",
            value="evening",
            content="旧",
            status="superseded",
            superseded_by_id=new_id,
            valid_from=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        SemanticMemoryState(
            id=new_id,
            subject_key="preferred_training_time",
            value="morning",
            content="新",
            status="active",
            superseded_by_id=None,
            valid_from=datetime(2026, 8, 27, tzinfo=UTC),
        ),
    )
    expectation = MemoryConflictExpectation(old_alias="old", new_alias="new")
    results = grade_memory_conflict(
        expectation,
        memories=memories,
        context_manifest={"semantic_memory_ids": [str(new_id)]},
        alias_ids={"old": old_id, "new": new_id},
    )
    assert all(item.passed for item in results)

    # 旧记忆仍被召回 → 新 Thread recall 失败。
    results = grade_memory_conflict(
        expectation,
        memories=memories,
        context_manifest={"semantic_memory_ids": [str(new_id), str(old_id)]},
        alias_ids={"old": old_id, "new": new_id},
    )
    recall = next(item for item in results if item.grader == "memory_conflict_new_thread_recall")
    assert not recall.passed
    assert recall.reason_code == "old_memory_still_retrieved"


def test_context_injection_grader_and_unknown_alias() -> None:
    """Context Injection：目标 ID 出现在 CONTEXT 清单；未知 alias 属配置错误。"""
    target_id = uuid4()
    results = grade_context_injection(
        ContextInjectionExpectation(semantic_required=["target"]),
        context_manifest={"semantic_memory_ids": [str(target_id)], "memory_policy_version": "phase4.v1"},
        alias_ids={"target": target_id},
    )
    assert all(item.passed for item in results)
    assert results[0].details["memory_policy_version"] == "phase4.v1"

    with pytest.raises(EvalConfigError):
        grade_context_injection(
            ContextInjectionExpectation(semantic_required=["missing_alias"]),
            context_manifest={"semantic_memory_ids": []},
            alias_ids={},
        )
