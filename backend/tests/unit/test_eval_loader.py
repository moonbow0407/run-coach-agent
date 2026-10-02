"""Eval Case Loader 的严格校验（PHASE 6 §9 / §23.1）。"""

from pathlib import Path

import pytest
import yaml

from app.evals.errors import EvalConfigError
from app.evals.loader import load_cases

_FIXTURE_CASES = Path(__file__).resolve().parents[1].parent / "app" / "evals" / "cases"


def _write(tmp_path: Path, docs: list[dict]) -> Path:
    """把 Case dict 序列化为临时 YAML 目录。"""
    (tmp_path / "cases.yaml").write_text(
        yaml.safe_dump({"cases": docs}, allow_unicode=True), encoding="utf-8"
    )
    return tmp_path


_BASE_AGENT_CASE = {
    "schema_version": "phase6.v1",
    "id": "tool_case_a",
    "suite": "tool",
    "execution": "real_agent",
    "fixture": "runner_vertical_slice",
    "turns": [{"input": "看看最近训练", "timestamp": "2026-08-28T10:00:00Z"}],
    "expectation": {"required_successful_tools": ["get_recent_workouts"]},
}


def test_real_case_files_load_and_are_fifteen() -> None:
    """仓库内 15 个正式 Case 全部通过严格校验。"""
    cases = load_cases()
    assert len(cases) == 15
    assert len({case.id for case in cases}) == 15


def test_unknown_field_rejected(tmp_path: Path) -> None:
    """未知字段一律拒绝（extra=forbid）。"""
    bad = {**_BASE_AGENT_CASE, "unexpected_field": 1}
    with pytest.raises(EvalConfigError):
        load_cases(_write(tmp_path, [bad]))


def test_unknown_schema_version_rejected(tmp_path: Path) -> None:
    """未知 schema version 在解析时失败。"""
    bad = {**_BASE_AGENT_CASE, "schema_version": "phase9.v1"}
    with pytest.raises(EvalConfigError):
        load_cases(_write(tmp_path, [bad]))


def test_duplicate_case_id_rejected(tmp_path: Path) -> None:
    """跨文件重复 Case ID 拒绝。"""
    duplicate = {**_BASE_AGENT_CASE, "id": "tool_case_a"}
    with pytest.raises(EvalConfigError, match="duplicate_case_id"):
        load_cases(_write(tmp_path, [_BASE_AGENT_CASE, duplicate]))


def test_unknown_fixture_rejected(tmp_path: Path) -> None:
    """不在白名单的 fixture 拒绝。"""
    bad = {**_BASE_AGENT_CASE, "fixture": "made_up_fixture"}
    with pytest.raises(EvalConfigError, match="unknown_fixture"):
        load_cases(_write(tmp_path, [bad]))


def test_naive_datetime_rejected(tmp_path: Path) -> None:
    """无时区时间拒绝。"""
    bad = {
        **_BASE_AGENT_CASE,
        "turns": [{"input": "x", "timestamp": "2026-08-28T10:00:00"}],
    }
    with pytest.raises(EvalConfigError):
        load_cases(_write(tmp_path, [bad]))


def test_expectation_must_match_suite(tmp_path: Path) -> None:
    """tool suite 不允许携带 coaching expectation（跨模式 expectation 拒绝）。"""
    bad = {**_BASE_AGENT_CASE, "expectation": {"must_create_plan_change": True}}
    with pytest.raises(EvalConfigError):
        load_cases(_write(tmp_path, [bad]))


def test_memory_retrieval_limit_cannot_exceed_production(tmp_path: Path) -> None:
    """retrieval 请求条数不允许突破生产上限。"""
    bad = {
        "schema_version": "phase6.v1",
        "id": "memory_case_a",
        "suite": "memory",
        "execution": "memory_retrieval",
        "fixture": "semantic_memory_distractors",
        "query": "查询",
        "as_of": "2026-08-28T08:00:00Z",
        "semantic_limit": 99,
        "expectation": {"semantic_required": ["weekday_evening_availability"]},
    }
    with pytest.raises(EvalConfigError):
        load_cases(_write(tmp_path, [bad]))


def test_empty_selection_rejected() -> None:
    """suite / case 过滤后为空立即失败。"""
    with pytest.raises(EvalConfigError, match="case_selection_empty"):
        load_cases(suite="coaching", case_id="tool_recent_001")  # 组合不相交
