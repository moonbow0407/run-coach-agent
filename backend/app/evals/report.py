"""Eval 结果模型、指标、JSON Artifact 与 Baseline Diff。

层级：EvalRunReport → EvalCaseResult → EvalTrialResult → EvalTurnResult。
状态聚合（PHASE 6 §16）：
- 全部 Trial PASS → PASS；全部 FAIL → FAIL；
- 同时存在 PASS 与 FAIL → UNSTABLE；任一 ERROR → ERROR。
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.evals.errors import EvalConfigError

REPORT_SCHEMA_VERSION = "phase6.v1"  # JSON artifact 顶层 schema 版本

# Trial / Case 的终态
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNSTABLE = "UNSTABLE"
STATUS_ERROR = "ERROR"

_TRACES_DIR = ".eval-results"

# JSON artifact 的敏感键脱敏规则：键名匹配即整个值替换为 [REDACTED]
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|jwt|token|password|secret|authorization|cookie|database[_-]?url|conn(?:ection)?[_-]?string)",
    re.IGNORECASE,
)


def redact_sensitive(value: Any) -> Any:
    """递归脱敏：键名命中敏感模式时丢弃原值，不携带环境变量或连接串。"""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY_PATTERN.search(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value


class TrialStatusValue(StrEnum):
    """Trial 终态。"""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass(frozen=True)
class EvalTurnResult:
    """单轮执行快照：身份 ID、上下文清单、完整轨迹与最终回答。"""

    thread_id: str | None  # 本轮所属 Thread（首轮后固定）
    turn_id: str  # 本轮 Turn
    run_id: str  # 本轮 AgentRun
    input: str  # 用户输入原文
    timestamp: str  # 业务时间（ISO）
    context_manifest: dict[str, Any] | None  # CONTEXT RunStep 清单
    run_steps: list[dict[str, Any]]  # 全部 RunStep（含工具参数与 Observation）
    final_answer: str | None  # 最终回答；自由文本只展示不评分
    duration_ms: int  # 本轮耗时


@dataclass(frozen=True)
class EvalTrialResult:
    """单次 Trial：轮次快照 + 全部 Grader 结论 + 终态。"""

    trial: int  # trial 序号（从 1 开始）
    status: str  # PASS / FAIL / ERROR
    grader_results: list[dict[str, Any]]  # 序列化后的 GradeResult
    turns: list[EvalTurnResult]
    error_code: str | None  # ERROR 时的稳定原因码
    error_message: str | None  # ERROR 时的安全错误说明
    duration_ms: int


@dataclass(frozen=True)
class EvalCaseResult:
    """一个 Case 的聚合结果。"""

    case_id: str
    suite: str
    fixture: str
    execution: str
    status: str  # PASS / FAIL / UNSTABLE / ERROR
    trials: list[EvalTrialResult]


@dataclass(frozen=True)
class RunProvenance:
    """运行溯源信息：模型、Prompt / 策略版本、git 状态与时间。"""

    configured_model: str | None
    prompt_version: str
    memory_policy_version: str
    git_sha: str
    git_dirty: bool
    started_at: str
    completed_at: str
    duration_ms: int
    trials: int


@dataclass(frozen=True)
class RunSummary:
    """总体指标：Raw Pass Rate 与 Suite Macro Score 并列展示。"""

    total_cases: int
    passed: int
    failed: int
    unstable: int
    errors: int  # ERROR 单独展示；不得被静默并入失败
    raw_case_pass_rate: float
    suite_macro_score: dict[str, float]
    tool_required_success_rate: float
    tool_discovery_success_rate: float
    forbidden_tool_attempt_rate: float
    semantic_recall_rate: float
    episode_recall_rate: float
    memory_conflict_accuracy: float
    context_injection_accuracy: float
    coaching_decision_accuracy: float


@dataclass(frozen=True)
class EvalRunReport:
    """一次 Eval Run 的完整报告。"""

    schema_version: str
    run_id: str
    selected_suites: list[str]
    selected_cases: list[str]
    provenance: RunProvenance
    summary: RunSummary
    case_results: list[EvalCaseResult]

    def to_json_dict(self) -> dict[str, Any]:
        """序列化为 JSON artifact 顶层结构（写入前统一脱敏）。"""
        return redact_sensitive(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "started_at": self.provenance.started_at,
                "completed_at": self.provenance.completed_at,
                "selected_suites": self.selected_suites,
                "selected_cases": self.selected_cases,
                "trials": self.provenance.trials,
                "configured_model": self.provenance.configured_model,
                "prompt_version": self.provenance.prompt_version,
                "memory_policy_version": self.provenance.memory_policy_version,
                "git_sha": self.provenance.git_sha,
                "git_dirty": self.provenance.git_dirty,
                "duration_ms": self.provenance.duration_ms,
                "summary": {
                    "total_cases": self.summary.total_cases,
                    "passed": self.summary.passed,
                    "failed": self.summary.failed,
                    "unstable": self.summary.unstable,
                    "errors": self.summary.errors,
                    "raw_case_pass_rate": self.summary.raw_case_pass_rate,
                    "suite_macro_score": self.summary.suite_macro_score,
                    "tool_required_success_rate": self.summary.tool_required_success_rate,
                    "tool_discovery_success_rate": self.summary.tool_discovery_success_rate,
                    "forbidden_tool_attempt_rate": self.summary.forbidden_tool_attempt_rate,
                    "semantic_recall_rate": self.summary.semantic_recall_rate,
                    "episode_recall_rate": self.summary.episode_recall_rate,
                    "memory_conflict_accuracy": self.summary.memory_conflict_accuracy,
                    "context_injection_accuracy": self.summary.context_injection_accuracy,
                    "coaching_decision_accuracy": self.summary.coaching_decision_accuracy,
                },
                "case_results": [_case_to_dict(case) for case in self.case_results],
            }
        )


def _case_to_dict(case: EvalCaseResult) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "fixture": case.fixture,
        "execution": case.execution,
        "status": case.status,
        "trials": [
            {
                "trial": trial.trial,
                "status": trial.status,
                "error_code": trial.error_code,
                "error_message": trial.error_message,
                "duration_ms": trial.duration_ms,
                "grader_results": trial.grader_results,
                "turns": [
                    {
                        "thread_id": turn.thread_id,
                        "turn_id": turn.turn_id,
                        "run_id": turn.run_id,
                        "input": turn.input,
                        "timestamp": turn.timestamp,
                        "context_manifest": turn.context_manifest,
                        "run_steps": turn.run_steps,
                        "final_answer": turn.final_answer,
                        "duration_ms": turn.duration_ms,
                    }
                    for turn in trial.turns
                ],
            }
            for trial in case.trials
        ],
    }


def aggregate_case_status(trial_statuses: list[str]) -> str:
    """按 §16 聚合 Case 状态：ERROR 优先，其次 PASS/FAIL 混合判 UNSTABLE。"""
    if not trial_statuses:
        raise EvalConfigError("case_has_no_trials")
    if any(status == STATUS_ERROR for status in trial_statuses):
        return STATUS_ERROR
    passed = all(status == STATUS_PASS for status in trial_statuses)
    if passed:
        return STATUS_PASS
    if all(status == STATUS_FAIL for status in trial_statuses):
        return STATUS_FAIL
    return STATUS_UNSTABLE


def grader_results_to_dicts(results: list[Any]) -> list[dict[str, Any]]:
    """GradeResult 列表 → JSON 结构。"""
    return [
        {
            "grader": item.grader,
            "passed": item.passed,
            "score": item.score,
            "reason_code": item.reason_code,
            "details": item.details,
        }
        for item in results
    ]


def build_summary(case_results: list[EvalCaseResult]) -> RunSummary:
    """从 Case 结果计算 Raw Pass Rate、Suite Macro Score 与辅助指标。"""
    cases = case_results
    total = len(cases)
    passed = sum(1 for case in cases if case.status == STATUS_PASS)
    failed = sum(1 for case in cases if case.status == STATUS_FAIL)
    unstable = sum(1 for case in cases if case.status == STATUS_UNSTABLE)
    errors = sum(1 for case in cases if case.status == STATUS_ERROR)

    suites: dict[str, list[float]] = {}
    for case in cases:
        suites.setdefault(case.suite, []).append(1.0 if case.status == STATUS_PASS else 0.0)
    macro = {
        suite: (sum(scores) / len(scores) if scores else 0.0)
        for suite, scores in sorted(suites.items())
    }

    graders = [
        grader
        for case in cases
        for trial in case.trials
        if trial.status != STATUS_ERROR
        for grader in trial.grader_results
    ]

    def _rate(grader_name: str) -> float:
        matched = [grader for grader in graders if grader["grader"] == grader_name]
        if not matched:
            return 0.0
        return sum(1 for grader in matched if grader["passed"]) / len(matched)

    forbidden = [
        grader
        for case in cases
        if case.suite == "tool"
        for trial in case.trials
        if trial.status != STATUS_ERROR
        for grader in trial.grader_results
        if grader["grader"] == "tool_forbidden_attempt"
    ]
    forbidden_rate = (
        sum(
            1
            for grader in forbidden
            if grader["details"].get("forbidden_hits")
        )
        / len(forbidden)
        if forbidden
        else 0.0
    )
    # Coaching Decision Accuracy：正例看“是否创建”，负例看“是否未创建”，取平均。
    decision_graders = [
        grader
        for grader in graders
        if grader["grader"] in {"coaching_plan_change_created", "coaching_no_plan_change"}
    ]
    coaching_accuracy = (
        sum(1 for grader in decision_graders if grader["passed"]) / len(decision_graders)
        if decision_graders
        else 0.0
    )
    return RunSummary(
        total_cases=total,
        passed=passed,
        failed=failed,
        unstable=unstable,
        errors=errors,
        raw_case_pass_rate=passed / total if total else 0.0,
        suite_macro_score=macro,
        tool_required_success_rate=_rate("tool_required_success"),
        tool_discovery_success_rate=_rate("tool_discovery"),
        forbidden_tool_attempt_rate=forbidden_rate,
        semantic_recall_rate=_rate("semantic_recall"),
        episode_recall_rate=_rate("episode_recall"),
        memory_conflict_accuracy=_rate("memory_conflict_lifecycle"),
        context_injection_accuracy=_rate("context_injection"),
        coaching_decision_accuracy=coaching_accuracy,
    )


def write_report_json(report: EvalRunReport, output_path: Path) -> Path:
    """把报告写入 JSON artifact；父目录不存在则创建。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2)
    output_path.write_text(payload, encoding="utf-8")
    return output_path


def default_output_path(started_at: datetime, git_sha: str) -> Path:
    """默认 artifact 路径：.eval-results/<UTC timestamp>-<short sha>.json。"""
    stamp = started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(_TRACES_DIR) / f"{stamp}-{git_sha[:8]}.json"


def exit_code_for(case_results: list[EvalCaseResult]) -> int:
    """CLI 退出码：0=全 PASS；1=存在 FAIL/UNSTABLE 且无 ERROR；2=存在 ERROR。"""
    if any(case.status == STATUS_ERROR for case in case_results):
        return 2
    if any(case.status in (STATUS_FAIL, STATUS_UNSTABLE) for case in case_results):
        return 1
    return 0


def load_baseline(path: Path) -> dict[str, Any]:
    """读取 baseline JSON 并校验 schema version 可识别。"""
    if not path.is_file():
        raise EvalConfigError(f"baseline_file_not_found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalConfigError("baseline_file_unreadable") from exc
    version = data.get("schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise EvalConfigError(f"baseline_schema_version_unrecognized: {version!r}")
    return data


def diff_against_baseline(
    current: EvalRunReport, baseline: dict[str, Any], *, baseline_path: str
) -> dict[str, Any]:
    """Baseline 差异：新增失败 / 恢复 / 稳定性变化 / Suite 指标变化 / 配置差异。"""
    base_cases = {
        item["case_id"]: item for item in baseline.get("case_results", [])
    }
    current_cases = {case.case_id: case for case in current.case_results}
    added = sorted(set(current_cases) - set(base_cases))
    removed = sorted(set(base_cases) - set(current_cases))

    new_failures: list[str] = []
    recovered: list[str] = []
    stability_changes: list[dict[str, str]] = []
    for case_id, case in current_cases.items():
        before = base_cases.get(case_id)
        if before is None:
            continue
        before_status = before["status"]
        if case.status == STATUS_FAIL and before_status in (STATUS_PASS, STATUS_UNSTABLE):
            new_failures.append(case_id)
        if case.status == STATUS_PASS and before_status == STATUS_FAIL:
            recovered.append(case_id)
        if {before_status, case.status} == {STATUS_PASS, STATUS_UNSTABLE}:
            stability_changes.append(
                {"case_id": case_id, "from": before_status, "to": case.status}
            )

    base_summary = baseline.get("summary", {})
    suite_delta = {
        suite: round(
            current.summary.suite_macro_score.get(suite, 0.0)
            - float(base_summary.get("suite_macro_score", {}).get(suite, 0.0)),
            4,
        )
        for suite in sorted(
            set(current.summary.suite_macro_score)
            | set(base_summary.get("suite_macro_score", {}))
        )
    }
    config_differences = _config_differences(current, baseline)
    return {
        "baseline_path": baseline_path,
        "added_cases": added,
        "removed_cases": removed,
        "new_failures": sorted(new_failures),
        "recovered_cases": sorted(recovered),
        "stability_changes": stability_changes,
        "suite_metric_delta": suite_delta,
        "config_differences": config_differences,
        "warning": "配置不同的比较只作展示参考" if config_differences else None,
    }


def _config_differences(current: EvalRunReport, baseline: dict[str, Any]) -> list[dict[str, str]]:
    """模型 / Prompt / Memory policy / git 差异：只告警，不禁止比较。"""
    pairs = (
        ("configured_model", current.provenance.configured_model, baseline.get("configured_model")),
        ("prompt_version", current.provenance.prompt_version, baseline.get("prompt_version")),
        (
            "memory_policy_version",
            current.provenance.memory_policy_version,
            baseline.get("memory_policy_version"),
        ),
        ("git_sha", current.provenance.git_sha, baseline.get("git_sha")),
        ("git_dirty", current.provenance.git_dirty, baseline.get("git_dirty")),
        ("trials", current.provenance.trials, baseline.get("trials")),
    )
    return [
        {"field": name, "current": _show(now), "baseline": _show(before)}
        for name, now, before in pairs
        if now != before
    ]


def _show(value: Any) -> str:
    return "None" if value is None else str(value)


def render_cli_summary(
    report: EvalRunReport, baseline_diff: dict[str, Any] | None, *, note: str
) -> str:
    """人类可读的终端报告：结果总表 + 指标 + baseline diff。"""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"Run Coach Eval Report  run_id={report.run_id}")
    lines.append(
        f"model={report.provenance.configured_model} prompt={report.provenance.prompt_version}"
        f" memory_policy={report.provenance.memory_policy_version}"
    )
    lines.append(
        f"git={report.provenance.git_sha[:8]} dirty={report.provenance.git_dirty}"
        f" trials={report.provenance.trials} duration={report.provenance.duration_ms}ms"
    )
    lines.append("=" * 72)
    lines.append(f"{'Case':<38}{'Suite':<10}{'Status':<12}Trials")
    lines.append("-" * 72)
    for case in report.case_results:
        trial_states = "/".join(trial.status for trial in case.trials)
        lines.append(f"{case.case_id:<38}{case.suite:<10}{case.status:<12}{trial_states}")
    lines.append("-" * 72)
    summary = report.summary
    lines.append(
        f"Raw Case Pass Rate: {summary.raw_case_pass_rate:.2%}"
        f"  (pass={summary.passed} fail={summary.failed} unstable={summary.unstable}"
        f" ERROR={summary.errors}/{summary.total_cases})"
    )
    macro = "  ".join(
        f"{suite}={score:.2f}" for suite, score in summary.suite_macro_score.items()
    )
    lines.append(f"Suite Macro Score:  {macro}")
    lines.append(
        f"tool_required={summary.tool_required_success_rate:.2%}"
        f" discovery={summary.tool_discovery_success_rate:.2%}"
        f" forbidden_attempt={summary.forbidden_tool_attempt_rate:.2%}"
    )
    lines.append(
        f"semantic_recall@limit={summary.semantic_recall_rate:.2%}"
        f" episode_recall@limit={summary.episode_recall_rate:.2%}"
        f" conflict={summary.memory_conflict_accuracy:.2%}"
    )
    lines.append(
        f"context_injection={summary.context_injection_accuracy:.2%}"
        f" coaching={summary.coaching_decision_accuracy:.2%}"
    )
    if baseline_diff is not None:
        lines.append("-" * 72)
        lines.append(
            f"Baseline diff: new_failures={baseline_diff['new_failures']}"
            f" recovered={baseline_diff['recovered_cases']}"
        )
        lines.append(f"stability_changes={baseline_diff['stability_changes']}")
        lines.append(f"suite_metric_delta={baseline_diff['suite_metric_delta']}")
        if baseline_diff["config_differences"]:
            lines.append(f"config_differences={baseline_diff['config_differences']}")
    lines.append("-" * 72)
    lines.append(note)
    return "\n".join(lines)
