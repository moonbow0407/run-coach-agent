"""Eval Case Loader：YAML → 严格 Pydantic 校验 → 跨 Case 校验。

加载阶段拒绝：重复 Case ID、未知 fixture、未知 schema version、非法结构
（extra=forbid 在模型层完成）；suite / case 过滤后为空立即失败。
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from app.evals.errors import EvalConfigError
from app.evals.fixtures import FIXTURES
from app.evals.models import EvalCaseUnion

_CASES_DIR = Path(__file__).resolve().parent / "cases"

_case_adapter = TypeAdapter(EvalCaseUnion)


def load_case_documents(directory: Path | None = None) -> list[tuple[str, dict[str, Any]]]:
    """读取目录下全部 YAML，返回 (来源文件名, 原始 dict)。"""
    root = directory or _CASES_DIR
    if not root.is_dir():
        raise EvalConfigError(f"eval_cases_dir_missing: {root}")
    documents: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise EvalConfigError(f"eval_case_yaml_invalid: {path.name}") from exc
        entries = data.get("cases") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise EvalConfigError(f"eval_case_file_shape_invalid: {path.name}")
        for entry in entries:
            documents.append((path.name, entry))
    return documents


def load_cases(
    directory: Path | None = None,
    *,
    suite: str | None = None,
    case_id: str | None = None,
) -> list[Any]:
    """加载并校验全部 Case，按 suite / case 过滤；过滤后为空立即失败。"""
    seen: set[str] = set()
    cases: list[Any] = []
    for filename, entry in load_case_documents(directory):
        if not isinstance(entry, dict):
            raise EvalConfigError(f"eval_case_entry_invalid: {filename}")
        try:
            case = _case_adapter.validate_python(entry)
        except Exception as exc:
            raise EvalConfigError(f"eval_case_validation_failed: {filename}: {exc}") from exc
        if case.id in seen:
            raise EvalConfigError(f"duplicate_case_id: {case.id}")
        seen.add(case.id)
        if case.fixture not in FIXTURES:
            raise EvalConfigError(f"unknown_fixture: {case.fixture}")
        cases.append(case)

    if suite is not None:
        cases = [case for case in cases if case.suite == suite]
    if case_id is not None:
        cases = [case for case in cases if case.id == case_id]
    if not cases:
        raise EvalConfigError("case_selection_empty")
    return cases
