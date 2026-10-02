"""确定性 Grader：全部评分基于生产 Trace / Context / Domain State，不调用模型。

约定（PHASE 6 §14）：
- Tool Grader 区分“尝试调用”与“执行成功”；forbidden 工具只要出现 tool_call 即失败；
- Discovery 必须同时证明 search 命中与目标工具后续执行成功；
- Coaching Outcome 必须与当前 Case 的 source turn/run 关联；
- 未知 alias 属于 Eval 配置错误（EvalConfigError），不是行为 FAIL。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.coaching.domain.plan.models import PlanChangeStatus
from app.evals.errors import EvalConfigError
from app.evals.models import (
    CoachingExpectation,
    ContextInjectionExpectation,
    MemoryConflictExpectation,
    MemoryRetrievalExpectation,
    ToolExpectation,
)
from app.evals.trace import EvalTrace
from app.infrastructure.evals.readers import (
    ActivePlanState,
    PlanChangeState,
    SemanticMemoryState,
)


@dataclass(frozen=True)
class GradeResult:
    """单个 Grader 的评分结论。"""

    grader: str  # grader 标识（对应指标归类）
    passed: bool
    score: float  # 1.0 通过 / 0.0 失败
    reason_code: str  # 通过为 ok；失败为稳定原因码
    details: dict[str, object]  # 证据细节（可序列化，进入 JSON artifact）


def grade_tool_expectation(
    expectation: ToolExpectation, trace: EvalTrace
) -> list[GradeResult]:
    """按成功 Observation / 尝试名单 / 发现顺序 / 步数上限评分。"""
    results: list[GradeResult] = []
    attempted = [call.tool for call in trace.attempted_tool_calls]
    successful = set(trace.successful_tools())

    for tool in expectation.required_successful_tools:
        passed = tool in successful
        results.append(
            GradeResult(
                grader="tool_required_success",
                passed=passed,
                score=1.0 if passed else 0.0,
                reason_code="ok" if passed else "required_tool_not_successful",
                details={"tool": tool, "successful_tools": sorted(successful)},
            )
        )

    forbidden_hits = [tool for tool in expectation.forbidden_tool_attempts if tool in attempted]
    results.append(
        GradeResult(
            grader="tool_forbidden_attempt",
            passed=not forbidden_hits,
            score=1.0 if not forbidden_hits else 0.0,
            reason_code="ok" if not forbidden_hits else "forbidden_tool_attempted",
            details={
                "forbidden_hits": forbidden_hits,
                "attempted_tools": attempted,
                # 尝试即失败的语义与执行结果无关：即使 Runtime 拒绝也算。
                "note": "attempt_alone_is_failure",
            },
        )
    )

    for target in expectation.required_discoveries:
        search_indexes = trace.search_hit_step_indexes(target)
        success_index = trace.success_observation_index(target)
        # Discovery 成功 = search 命中 且 目标在其后执行成功。
        passed = (
            bool(search_indexes)
            and success_index is not None
            and success_index > search_indexes[0]
        )
        results.append(
            GradeResult(
                grader="tool_discovery",
                passed=passed,
                score=1.0 if passed else 0.0,
                reason_code="ok"
                if passed
                else (
                    "discovery_search_missed_target"
                    if not search_indexes
                    else "discovered_tool_not_executed_successfully"
                ),
                details={
                    "target": target,
                    "search_hit_indexes": search_indexes,
                    "success_index": success_index,
                },
            )
        )

    if expectation.max_tool_attempts is not None:
        count = len(attempted)
        passed = count <= expectation.max_tool_attempts
        results.append(
            GradeResult(
                grader="tool_attempt_budget",
                passed=passed,
                score=1.0 if passed else 0.0,
                reason_code="ok" if passed else "too_many_tool_attempts",
                details={"attempts": count, "max": expectation.max_tool_attempts},
            )
        )
    return results


def grade_memory_retrieval(
    expectation: MemoryRetrievalExpectation,
    result: Any,
    *,
    alias_ids: Mapping[str, UUID],
) -> list[GradeResult]:
    """按最终入选集合评分（Recall@ConfiguredLimit 口径）。"""
    semantic_ids = {item.id for item in result.semantic}
    episodic_ids = {item.id for item in result.episodic}
    results: list[GradeResult] = []
    for grader, required, forbidden, selected, label in (
        (
            "semantic_recall",
            expectation.semantic_required,
            expectation.semantic_forbidden,
            semantic_ids,
            "semantic",
        ),
        (
            "episode_recall",
            expectation.episodic_required,
            expectation.episodic_forbidden,
            episodic_ids,
            "episodic",
        ),
    ):
        if not required and not forbidden:
            continue
        required_ids = [_resolve(alias, alias_ids) for alias in required]
        forbidden_ids = [_resolve(alias, alias_ids) for alias in forbidden]
        missing = [alias for alias, mid in zip(required, required_ids) if mid not in selected]
        leaked = [alias for alias, mid in zip(forbidden, forbidden_ids) if mid in selected]
        passed = not missing and not leaked
        results.append(
            GradeResult(
                grader=grader,
                passed=passed,
                score=1.0 if passed else 0.0,
                reason_code="ok"
                if passed
                else ("required_memory_missing" if missing else "forbidden_memory_selected"),
                details={
                    "side": label,
                    "missing_required": missing,
                    "leaked_forbidden": leaked,
                    "policy_version": result.policy_version,
                    "truncated": {
                        "semantic": result.semantic_truncated,
                        "episodic": result.episodic_truncated,
                    },
                    "selected_count": len(selected),
                },
            )
        )
    return results


def grade_memory_conflict(
    expectation: MemoryConflictExpectation,
    *,
    memories: tuple[SemanticMemoryState, ...],
    context_manifest: Mapping[str, Any] | None,
    alias_ids: Mapping[str, UUID],
) -> list[GradeResult]:
    """旧记忆被取代 + 新 Thread 检索只召回新知识，两部分都必须成立。"""
    old_id = _resolve(expectation.old_alias, alias_ids)
    new_id = _resolve(expectation.new_alias, alias_ids)
    by_id = {state.id: state for state in memories}
    old_state = by_id.get(old_id)
    new_state = by_id.get(new_id)
    if old_state is None or new_state is None:
        raise EvalConfigError("memory_conflict_alias_unresolved_in_domain_state")

    lifecycle_ok = (
        old_state.status == "superseded"
        and new_state.status == "active"
        and old_state.superseded_by_id == new_id
    )
    lifecycle = GradeResult(
        grader="memory_conflict_lifecycle",
        passed=lifecycle_ok,
        score=1.0 if lifecycle_ok else 0.0,
        reason_code="ok" if lifecycle_ok else "memory_lifecycle_incomplete",
        details={
            "old": {
                "status": old_state.status,
                "superseded_by_id": str(old_state.superseded_by_id),
            },
            "new": {"status": new_state.status},
        },
    )

    semantic_ids = _manifest_ids(context_manifest, "semantic_memory_ids")
    recall_ok = new_id in semantic_ids and old_id not in semantic_ids
    recall = GradeResult(
        grader="memory_conflict_new_thread_recall",
        passed=recall_ok,
        score=1.0 if recall_ok else 0.0,
        reason_code="ok"
        if recall_ok
        else (
            "new_memory_not_retrieved"
            if new_id not in semantic_ids
            else "old_memory_still_retrieved"
        ),
        details={
            "new_injected": new_id in semantic_ids,
            "old_injected": old_id in semantic_ids,
            "semantic_memory_ids": [str(item) for item in semantic_ids],
        },
    )
    return [lifecycle, recall]


def grade_context_injection(
    expectation: ContextInjectionExpectation,
    *,
    context_manifest: Mapping[str, Any] | None,
    alias_ids: Mapping[str, UUID],
) -> list[GradeResult]:
    """目标记忆 ID 必须真实出现在 CONTEXT RunStep 的注入清单中。"""
    semantic_ids = _manifest_ids(context_manifest, "semantic_memory_ids")
    episodic_ids = _manifest_ids(context_manifest, "episodic_memory_ids")
    results: list[GradeResult] = []
    for required, selected, label in (
        (expectation.semantic_required, semantic_ids, "semantic"),
        (expectation.episodic_required, episodic_ids, "episodic"),
    ):
        if not required:
            continue
        required_ids = [_resolve(alias, alias_ids) for alias in required]
        missing = [alias for alias, mid in zip(required, required_ids) if mid not in selected]
        passed = not missing
        results.append(
            GradeResult(
                grader="context_injection",
                passed=passed,
                score=1.0 if passed else 0.0,
                reason_code="ok" if passed else "memory_not_injected",
                details={
                    "side": label,
                    "missing": missing,
                    "memory_policy_version": (context_manifest or {}).get(
                        "memory_policy_version"
                    ),
                    "semantic_truncated": (context_manifest or {}).get("semantic_truncated"),
                    "episodic_truncated": (context_manifest or {}).get("episodic_truncated"),
                },
            )
        )
    if not results:
        raise EvalConfigError("context_injection_expectation_empty")
    return results


def grade_coaching_decision(
    expectation: CoachingExpectation,
    *,
    plan_changes: tuple[PlanChangeState, ...],
    active_plan: ActivePlanState | None,
    fixture_plan_id: UUID,
    fixture_plan_version: int,
    fixture_state_version: int,
    turn_id: UUID,
    run_id: UUID,
) -> list[GradeResult]:
    """正例要求本 Run 创建 pending 提案且 Active Plan 未变；负例要求不创建。"""
    sourced = [
        change
        for change in plan_changes
        # 只认当前 Case 的 source identity：读“最新 PlanChange”不足以证明结果。
        if change.source_turn_id == turn_id and change.source_run_id == run_id
    ]
    results: list[GradeResult] = []
    if expectation.must_create_plan_change:
        exists = len(sourced) == 1
        results.append(
            GradeResult(
                grader="coaching_plan_change_created",
                passed=exists,
                score=1.0 if exists else 0.0,
                reason_code="ok" if exists else "plan_change_not_created_for_current_run",
                details={"sourced_count": len(sourced)},
            )
        )
        change = sourced[0] if exists else None
        pending = change is not None and change.status is PlanChangeStatus.PENDING_CONFIRMATION
        results.append(
            GradeResult(
                grader="coaching_plan_change_pending",
                passed=pending,
                score=1.0 if pending else 0.0,
                reason_code="ok" if pending else "plan_change_not_pending_after_drain",
                details={"status": change.status.value if change else None},
            )
        )
        grounded = (
            change is not None
            and bool(change.reason.strip())
            and change.from_plan_id == fixture_plan_id
            and change.from_plan_version == fixture_plan_version
            and change.based_on_state_version == fixture_state_version
        )
        results.append(
            GradeResult(
                grader="coaching_plan_change_grounded",
                passed=grounded,
                score=1.0 if grounded else 0.0,
                reason_code="ok" if grounded else "plan_change_grounded_on_wrong_versions",
                details={
                    "reason_non_empty": bool(change is not None and change.reason.strip()),
                    "from_plan_id": str(change.from_plan_id) if change else None,
                    "from_plan_version": change.from_plan_version if change else None,
                    "based_on_state_version": change.based_on_state_version if change else None,
                },
            )
        )
    else:
        results.append(
            GradeResult(
                grader="coaching_no_plan_change",
                passed=not sourced,
                score=1.0 if not sourced else 0.0,
                reason_code="ok" if not sourced else "plan_change_created_for_current_run",
                details={"sourced_count": len(sourced)},
            )
        )

    active_unchanged = (
        active_plan is not None
        and active_plan.plan_id == fixture_plan_id
        and active_plan.version == fixture_plan_version
    )
    results.append(
        GradeResult(
            grader="coaching_active_plan_unchanged",
            passed=active_unchanged,
            score=1.0 if active_unchanged else 0.0,
            reason_code="ok" if active_unchanged else "active_plan_changed",
            details={
                "active_plan_id": str(active_plan.plan_id) if active_plan else None,
                "active_plan_version": active_plan.version if active_plan else None,
                "fixture_plan_id": str(fixture_plan_id),
                "fixture_plan_version": fixture_plan_version,
            },
        )
    )
    return results


def _resolve(alias: str, alias_ids: Mapping[str, UUID]) -> UUID:
    """alias → 真实 UUID；未知 alias 属于配置错误，在评分前失败。"""
    try:
        return alias_ids[alias]
    except KeyError:
        raise EvalConfigError(f"unknown_fixture_alias: {alias}") from None


def _manifest_ids(manifest: Mapping[str, Any] | None, key: str) -> set[UUID]:
    """从 CONTEXT 清单读取记忆 ID 集合（JSON 中为字符串形式）。"""
    if not manifest:
        return set()
    values = manifest.get(key) or []
    return {UUID(str(item)) for item in values}
