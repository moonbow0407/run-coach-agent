"""Eval CLI 入口：uv run python -m app.evals.cli run [options]。

退出码（PHASE 6 §18）：
- 0 = 全部 Case PASS；
- 1 = 至少一个 FAIL / UNSTABLE，且没有 ERROR；
- 2 = 至少一个 ERROR，或启动 / 配置 / Schema 失败。
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from app.evals.environment import (
    load_base_settings,
    load_eval_settings,
    reset_eval_database,
    resolve_eval_database_url,
    upgrade_eval_schema,
    validate_eval_database_url,
)
from app.evals.errors import EvalError
from app.evals.loader import load_cases
from app.evals.report import (
    default_output_path,
    diff_against_baseline,
    exit_code_for,
    load_baseline,
    render_cli_summary,
    write_report_json,
)
from app.evals.runner import EvalRunner
from app.infrastructure.logging import configure_logging

_FINAL_NOTE = (
    "PASS 表示 Trace、Context 与 Domain Outcome 满足 Case 预期，"
    "不代表语言质量或完整事实一致性已经通过评估。"
)


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数：run 子命令 + suite/case/trials/model/baseline/output。"""
    parser = argparse.ArgumentParser(prog="app.evals.cli", description="Run Coach Agent Eval")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="执行 Eval Case")
    run.add_argument("--suite", choices=["tool", "memory", "coaching"], default=None)
    run.add_argument("--case", dest="case_id", default=None, help="只运行指定 Case ID")
    run.add_argument("--trials", type=int, default=1, help="每个 Case 的 Trial 次数（默认 1）")
    run.add_argument("--model", default=None, help="覆盖本次 Eval 的 LLM 模型配置")
    run.add_argument("--baseline", default=None, help="用于比较的 baseline JSON 报告")
    run.add_argument("--output", default=None, help="JSON artifact 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：环境校验失败返回 2；FAIL/UNSTABLE 返回 1；全 PASS 返回 0。"""
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command != "run":  # pragma: no cover - argparse 已约束
        return _exit(2, "未知子命令")
    if args.trials < 1:
        return _exit(2, "--trials 必须大于 0")
    try:
        cases = load_cases(suite=args.suite, case_id=args.case_id)
        exit_code = asyncio.run(_run(args, cases))
    except EvalError as exc:
        return _exit(2, f"[eval-error] {getattr(exc, 'code', 'eval_failed')}: {exc}")
    except Exception as exc:  # noqa: BLE001 - CLI 顶层边界归一化
        return _exit(2, f"[startup-failed] {type(exc).__name__}: {exc}")
    return exit_code


async def _run(args: argparse.Namespace, cases: list) -> int:
    """完整 Run：守卫 → migration → 重置 → 执行 → 报告 → baseline diff。"""
    base_settings = load_base_settings()
    settings = load_eval_settings(model_override=args.model)
    eval_url = resolve_eval_database_url()
    # 任何 migration / 清理之前的严格防误连校验：对照 .env 原始业务库 URL。
    validate_eval_database_url(eval_url, settings=base_settings)
    await upgrade_eval_schema(eval_url)
    engine = create_async_engine(eval_url)
    try:
        await reset_eval_database(engine)
    finally:
        await engine.dispose()

    report = await EvalRunner(settings).run(cases, trials=args.trials)

    output = Path(args.output) if args.output else default_output_path(
        datetime.now(UTC), report.provenance.git_sha
    )
    write_report_json(report, output)

    baseline_diff = None
    if args.baseline:
        baseline = load_baseline(Path(args.baseline))
        baseline_diff = diff_against_baseline(
            report, baseline, baseline_path=str(args.baseline)
        )
    print(render_cli_summary(report, baseline_diff, note=_FINAL_NOTE))
    print(f"JSON artifact: {output}")
    return exit_code_for(report.case_results)


def _exit(code: int, message: str) -> int:
    print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
