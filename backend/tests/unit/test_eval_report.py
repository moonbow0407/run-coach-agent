"""Eval 报告：Trial/Case 聚合、指标、脱敏与 baseline diff（PHASE 6 §16-§19 / §23.1）。"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.evals.errors import EvalConfigError
from app.evals.report import (
    EvalCaseResult,
    EvalRunReport,
    EvalTrialResult,
    RunProvenance,
    RunSummary,
    aggregate_case_status,
    build_summary,
    default_output_path,
    diff_against_baseline,
    exit_code_for,
    load_baseline,
    redact_sensitive,
    write_report_json,
)


def _grader(name: str, passed: bool, details: dict | None = None) -> dict:
    return {
        "grader": name,
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason_code": "ok" if passed else "failed",
        "details": details or {},
    }


def _trial(trial: int, status: str, graders: list[dict]) -> EvalTrialResult:
    return EvalTrialResult(
        trial=trial,
        status=status,
        grader_results=graders,
        turns=[],
        error_code=None if status != "ERROR" else "boom",
        error_message=None if status != "ERROR" else "环境失败",
        duration_ms=1,
    )


def _case(case_id: str, suite: str, trials: list[EvalTrialResult]) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        suite=suite,
        fixture="runner_vertical_slice",
        execution="real_agent",
        status=aggregate_case_status([trial.status for trial in trials]),
        trials=trials,
    )


def _provenance() -> RunProvenance:
    now = datetime.now(UTC).isoformat()
    return RunProvenance(
        configured_model="test-model",
        prompt_version="phase6.v1",
        memory_policy_version="phase4.v1",
        git_sha="abcdef1234567890",
        git_dirty=False,
        started_at=now,
        completed_at=now,
        duration_ms=10,
        trials=1,
    )


def _summary() -> RunSummary:
    return RunSummary(
        total_cases=0,
        passed=0,
        failed=0,
        unstable=0,
        errors=0,
        raw_case_pass_rate=0.0,
        suite_macro_score={},
        tool_required_success_rate=0.0,
        tool_discovery_success_rate=0.0,
        forbidden_tool_attempt_rate=0.0,
        semantic_recall_rate=0.0,
        episode_recall_rate=0.0,
        memory_conflict_accuracy=0.0,
        context_injection_accuracy=0.0,
        coaching_decision_accuracy=0.0,
    )


def test_multi_trial_aggregation_rules() -> None:
    """PASS / FAIL / UNSTABLE / ERROR 聚合语义。"""
    assert aggregate_case_status(["PASS"]) == "PASS"
    assert aggregate_case_status(["FAIL"]) == "FAIL"
    assert aggregate_case_status(["PASS", "FAIL"]) == "UNSTABLE"
    assert aggregate_case_status(["PASS", "PASS", "FAIL"]) == "UNSTABLE"
    assert aggregate_case_status(["PASS", "ERROR"]) == "ERROR"
    with pytest.raises(EvalConfigError):
        aggregate_case_status([])


def test_raw_pass_rate_and_suite_macro_score() -> None:
    """Raw Case Pass Rate 等权 15 Case；Suite Macro 三个 Suite 等权。"""
    cases = [
        _case("tool_a", "tool", [_trial(1, "PASS", [_grader("tool_required_success", True)])]),
        _case("tool_b", "tool", [_trial(1, "FAIL", [_grader("tool_required_success", False)])]),
        _case("tool_c", "tool", [_trial(1, "PASS", [])]),
        _case("tool_d", "tool", [_trial(1, "PASS", [])]),
        _case("tool_e", "tool", [_trial(1, "PASS", [])]),
        _case("tool_f", "tool", [_trial(1, "PASS", [])]),
        _case("tool_g", "tool", [_trial(1, "PASS", [])]),
        _case("memory_a", "memory", [_trial(1, "FAIL", [_grader("semantic_recall", False)])]),
        _case("memory_b", "memory", [_trial(1, "PASS", [])]),
        _case("memory_c", "memory", [_trial(1, "PASS", [])]),
        _case("memory_d", "memory", [_trial(1, "PASS", [])]),
        _case("memory_e", "memory", [_trial(1, "PASS", [])]),
        _case("coaching_a", "coaching", [_trial(1, "FAIL", [_grader("coaching_no_plan_change", True)])]),
        _case("coaching_b", "coaching", [_trial(1, "PASS", [])]),
        _case("coaching_c", "coaching", [_trial(1, "PASS", [])]),
    ]
    summary = build_summary(cases)
    assert summary.total_cases == 15
    assert summary.passed == 12
    assert summary.failed == 3
    assert summary.errors == 0
    assert summary.raw_case_pass_rate == pytest.approx(12 / 15)
    # Tool 6/7，Memory 4/5，Coaching 2/3 → macro 三者平均。
    assert summary.suite_macro_score["tool"] == pytest.approx(6 / 7)
    assert summary.suite_macro_score["memory"] == pytest.approx(4 / 5)
    assert summary.suite_macro_score["coaching"] == pytest.approx(2 / 3)
    assert summary.tool_required_success_rate == pytest.approx(0.5)
    # 正例判定 grader 不存在 → 只统计负例判定。
    assert summary.coaching_decision_accuracy == 1.0


def test_error_is_counted_separately_not_as_fail() -> None:
    """ERROR 不计为行为失败，但单独出现在 errors 数中。"""
    cases = [
        _case("tool_a", "tool", [_trial(1, "PASS", [])]),
        _case("memory_a", "memory", [_trial(1, "ERROR", [])]),
    ]
    summary = build_summary(cases)
    assert summary.errors == 1
    assert summary.failed == 0
    assert summary.raw_case_pass_rate == pytest.approx(0.5)


def test_sensitive_fields_redacted() -> None:
    """JSON artifact 敏感键统一脱敏。"""
    payload = {
        "llm_api_key": "sk-secret",
        "database_url": "postgresql://user:pass@host/db",
        "jwt": "token",
        "nested": {"Authorization": "Bearer x", "safe": 1},
        "items": [{"password": "p", "keep": "v"}],
    }
    redacted = redact_sensitive(payload)
    assert redacted["llm_api_key"] == "[REDACTED]"
    assert redacted["database_url"] == "[REDACTED]"
    assert redacted["jwt"] == "[REDACTED]"
    assert redacted["nested"]["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == 1
    assert redacted["items"][0]["password"] == "[REDACTED]"
    assert redacted["items"][0]["keep"] == "v"


def test_report_roundtrip_and_baseline_diff(tmp_path) -> None:
    """报告落盘可读，baseline diff 展示新增失败 / 恢复 / 稳定性 / 指标变化。"""
    cases_pass = [
        _case("tool_a", "tool", [_trial(1, "PASS", [])]),
        _case("memory_a", "memory", [_trial(1, "FAIL", [])]),  # baseline 中为 FAIL
        _case("coaching_a", "coaching", [_trial(1, "PASS", [])]),
    ]
    baseline_report = EvalRunReport(
        schema_version="phase6.v1",
        run_id=str(uuid4()),
        selected_suites=["tool", "memory", "coaching"],
        selected_cases=["tool_a", "memory_a", "coaching_a"],
        provenance=_provenance(),
        summary=build_summary(cases_pass),
        case_results=cases_pass,
    )
    baseline_path = tmp_path / "baseline.json"
    write_report_json(baseline_report, baseline_path)
    loaded = load_baseline(baseline_path)
    assert loaded["schema_version"] == "phase6.v1"

    cases_now = [
        # PASS → FAIL：新增失败
        _case("tool_a", "tool", [_trial(1, "FAIL", [])]),
        # FAIL → PASS：恢复
        _case("memory_a", "memory", [_trial(1, "PASS", [])]),
        # PASS → UNSTABLE：稳定性退化
        _case("coaching_a", "coaching", [_trial(1, "PASS", []), _trial(2, "FAIL", [])]),
    ]
    now = EvalRunReport(
        schema_version="phase6.v1",
        run_id=str(uuid4()),
        selected_suites=["tool", "memory", "coaching"],
        selected_cases=["tool_a", "memory_a", "coaching_a"],
        provenance=_provenance(),
        summary=build_summary(cases_now),
        case_results=cases_now,
    )
    diff = diff_against_baseline(now, loaded, baseline_path=str(baseline_path))
    assert diff["new_failures"] == ["tool_a"]
    assert diff["recovered_cases"] == ["memory_a"]
    assert diff["stability_changes"] == [
        {"case_id": "coaching_a", "from": "PASS", "to": "UNSTABLE"}
    ]
    assert diff["suite_metric_delta"]["tool"] == pytest.approx(-1.0)
    assert diff["config_differences"] == []

    with pytest.raises(EvalConfigError):
        load_baseline(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "phase1.v1"}), encoding="utf-8")
    with pytest.raises(EvalConfigError):
        load_baseline(bad)


def test_default_output_path_shape() -> None:
    """默认 artifact 路径形如 .eval-results/<UTC ts>-<short sha>.json。"""
    path = default_output_path(datetime(2026, 9, 1, 8, 0, tzinfo=UTC), "abcdef1234567890")
    assert str(path).startswith(".eval-results")
    assert path.name == "20260901T080000Z-abcdef12.json"


def test_cli_exit_code_mapping() -> None:
    """退出码：全 PASS=0；FAIL/UNSTABLE=1；任一 ERROR=2。"""
    assert exit_code_for([_case("a", "tool", [_trial(1, "PASS", [])])]) == 0
    both = [_case("a", "tool", [_trial(1, "PASS", [])]), _case("b", "tool", [_trial(1, "FAIL", [])])]
    assert exit_code_for(both) == 1
    assert exit_code_for([_case("a", "tool", [_trial(1, "PASS", []), _trial(2, "FAIL", [])])]) == 1
    assert exit_code_for([_case("a", "tool", [_trial(1, "ERROR", [])])]) == 2
    mixed = [_case("a", "tool", [_trial(1, "PASS", [])]), _case("b", "tool", [_trial(1, "ERROR", [])])]
    assert exit_code_for(mixed) == 2
