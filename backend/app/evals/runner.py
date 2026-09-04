"""Eval Runner：按 Case 执行方式编排 fixture、ChatService、一致性屏障与评分。

职责边界（PHASE 6 §7）：
- real_agent（Tool / Coaching）：ChatService + AgentRuntime + 真实 LLMReasoner；
- memory_retrieval：直接调用正式 Retrieval Service，不混入 Reasoner 噪音；
- memory_lifecycle：Case turns（ScriptedReasoner）→ 正式 Projection → 新 Thread 检索；
- context_injection：ScriptedReasoner 执行，评分目标发生在 Reasoner 调用之前。

任何 EvalError / 意外异常都归一化为该 Trial 的 ERROR，不会伪装成行为 FAIL。
"""

import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.pool import NullPool

from app.agent.models.action import FinalAction
from app.agent.models.run import AgentRunStatus
from app.bootstrap import AppContainer, build_container
from app.common.errors import RunCoachError
from app.evals.barrier import drain_durable_tasks
from app.evals.environment import EvalClock
from app.evals.errors import EvalConfigError, EvalEnvironmentError, EvalStateError
from app.evals.fixtures import FIXTURES, EvalFixtureRefs, noop_memory_extractor
from app.evals.graders import (
    GradeResult,
    grade_coaching_decision,
    grade_context_injection,
    grade_memory_conflict,
    grade_memory_retrieval,
    grade_tool_expectation,
)
from app.evals.models import EvalCase, case_execution, case_turns
from app.evals.report import (
    STATUS_FAIL,
    STATUS_PASS,
    EvalCaseResult,
    EvalRunReport,
    EvalTrialResult,
    EvalTurnResult,
    RunProvenance,
    aggregate_case_status,
    build_summary,
    grader_results_to_dicts,
)
from app.evals.trace import EvalTrace
from app.identity.application.request_context import RequestContext
from app.infrastructure.config import Settings
from app.infrastructure.evals.readers import (
    EvalAgentStateReader,
    EvalCoachingStateReader,
    EvalMemoryStateReader,
)
from app.infrastructure.jsonutil import json_ready

# 全部 Eval Case 的业务时间起点：fixture 与 turns 在此之后顺序推进。
CASE_TIME_BASE = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

REPORT_SCHEMA_VERSION = "phase6.v1"

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class EvalScriptedReasoner:
    """memory 模式的脚本化 Reasoner：不依赖模型，恒定给出固定最终回答。"""

    async def reason(self, context: object, on_text_delta=None) -> FinalAction:
        if on_text_delta is not None:
            await on_text_delta("好的。")
        return FinalAction(content="好的。")


@dataclass(frozen=True)
class _TurnExecution:
    """单轮执行产物：ChatService 结果 + 重建的轨迹视图。"""

    turn_input: str  # 用户输入原文
    timestamp: datetime  # 业务时间
    thread_id: UUID  # Thread UUID
    turn_id: UUID  # Turn UUID
    run_id: UUID  # AgentRun UUID
    trace: EvalTrace  # 只读轨迹视图（含 CONTEXT 清单）
    duration_ms: int  # 本轮墙钟耗时


class EvalRunner:
    """执行一组 Case 并产出 EvalRunReport。

    embedding_provider / reasoner 仅测试注入：生产路径一律使用 Settings 装配
    的真实实现，注入值存在时覆盖对应模式（reasoner 覆盖 real_agent 模式）。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_provider=None,
        reasoner=None,
    ) -> None:
        self._settings = settings
        self._embedding_provider = embedding_provider  # Embedding 替身（集成测试）
        self._reasoner = reasoner  # Reasoner 替身（集成测试真实 Agent 链路）

    async def run(self, cases: list[EvalCase], *, trials: int) -> EvalRunReport:
        """逐 Case 逐 Trial 执行并汇总；调用方负责已验证的 Eval 数据库。"""
        if trials < 1:
            raise EvalConfigError("trials_must_be_positive")
        run_id = uuid4()
        started = datetime.now(UTC)
        git_sha, git_dirty = _git_info()
        case_results = [await self._run_case(case, trials=trials) for case in cases]
        completed = datetime.now(UTC)
        return EvalRunReport(
            schema_version=REPORT_SCHEMA_VERSION,
            run_id=str(run_id),
            selected_suites=sorted({case.suite for case in cases}),
            selected_cases=[case.id for case in cases],
            provenance=RunProvenance(
                configured_model=self._settings.llm_model,
                prompt_version=_prompt_version(),
                memory_policy_version=_memory_policy_version(),
                git_sha=git_sha,
                git_dirty=git_dirty,
                started_at=started.isoformat(),
                completed_at=completed.isoformat(),
                duration_ms=int((completed - started).total_seconds() * 1000),
                trials=trials,
            ),
            summary=build_summary(case_results),
            case_results=case_results,
        )

    async def _run_case(self, case: EvalCase, *, trials: int) -> EvalCaseResult:
        trial_results = [await self._run_trial(case, trial=index) for index in range(1, trials + 1)]
        return EvalCaseResult(
            case_id=case.id,
            suite=case.suite,
            fixture=case.fixture,
            execution=case_execution(case),
            status=aggregate_case_status([trial.status for trial in trial_results]),
            trials=trial_results,
        )

    async def _run_trial(self, case: EvalCase, *, trial: int) -> EvalTrialResult:
        started = time.perf_counter()
        try:
            turns, grader_results = await self._execute_case(case)
            status = STATUS_PASS if all(item.passed for item in grader_results) else STATUS_FAIL
            return EvalTrialResult(
                trial=trial,
                status=status,
                grader_results=grader_results_to_dicts(grader_results),
                turns=turns,
                error_code=None,
                error_message=None,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except RunCoachError as exc:
            return _error_trial(
                trial, code=getattr(exc, "code", "eval_failed"), exc=exc, started=started
            )
        except Exception as exc:  # noqa: BLE001 - Trial 边界兜底：意外异常归一化为 ERROR
            # 意外异常按环境 ERROR 处理；不携带堆栈与基础设施细节。
            return _error_trial(trial, code="unexpected_error", exc=exc, started=started)

    async def _execute_case(
        self, case: EvalCase
    ) -> tuple[list[EvalTurnResult], list[GradeResult]]:
        """按执行方式分派：准备容器 → 执行 → 排空 → 评分；结束必须释放连接池。"""
        mode = case_execution(case)
        spec = FIXTURES.get(case.fixture)
        if spec is None:
            raise EvalConfigError(f"unknown_fixture: {case.fixture}")
        clock = EvalClock(CASE_TIME_BASE)
        if mode == "real_agent":
            reasoner = self._reasoner  # 测试注入；生产为 None → 容器装配真实 LLMReasoner
        else:
            reasoner = EvalScriptedReasoner()
        container = build_container(
            self._settings,
            clock=clock,
            poolclass=NullPool,
            reasoner=reasoner,
            memory_extractor=(
                spec.extractor_factory() if spec.extractor_factory else noop_memory_extractor()
            ),
            embedding_provider=self._embedding_provider,
        )
        try:
            user_id, ids = await spec.seed(container, clock)
            await drain_durable_tasks(container)
            if spec.resolve_ids is not None:
                ids = {**ids, **await spec.resolve_ids(container, user_id)}
            refs = EvalFixtureRefs(user_id=user_id, ids=ids)
            if mode == "real_agent":
                return await _execute_real_agent(case, container, clock, refs)
            if mode == "memory_retrieval":
                return await _execute_memory_retrieval(case, container, refs)
            if mode == "memory_lifecycle":
                return await _execute_memory_lifecycle(case, container, clock, refs)
            if mode == "context_injection":
                return await _execute_context_injection(case, container, clock, refs)
            raise EvalConfigError(f"unsupported_execution_mode: {mode}")
        finally:
            await container.engine.dispose()


def _error_trial(trial: int, *, code: str, exc: Exception, started: float) -> EvalTrialResult:
    """把异常归一化为 ERROR Trial：RunCoachError 保留安全消息，其余只留类型名。"""
    message = str(exc) if isinstance(exc, RunCoachError) else type(exc).__name__
    return EvalTrialResult(
        trial=trial,
        status="ERROR",
        grader_results=[],
        turns=[],
        error_code=code,
        error_message=message,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


async def _run_turns(
    *,
    container: AppContainer,
    clock: EvalClock,
    user_id: UUID,
    turns: list,
) -> list[_TurnExecution]:
    """顺序执行 Case turns：显式传递 thread_id 保持同一 Trial 的会话连续。"""
    executions: list[_TurnExecution] = []
    thread_id: UUID | None = None
    for turn in turns:
        clock.advance_to(turn.timestamp)
        context = RequestContext(
            user_id=user_id,
            request_id=uuid4(),
            trace_id=uuid4(),
            timestamp=turn.timestamp,
        )
        started = time.perf_counter()
        result = await container.chat_service.send_message(
            request_context=context,
            thread_id=thread_id,
            content=turn.input,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        thread_id = result.thread_id
        executions.append(
            _TurnExecution(
                turn_input=turn.input,
                timestamp=turn.timestamp,
                thread_id=result.thread_id,
                turn_id=result.turn_id,
                run_id=result.run_id,
                trace=await _load_trace(container, user_id, result.run_id),
                duration_ms=duration_ms,
            )
        )
    return executions


async def _load_trace(container: AppContainer, user_id: UUID, run_id: UUID) -> EvalTrace:
    """经生产 TraceReader 读取轨迹并按 Run 终态重建 EvalTrace。"""
    run_state = await EvalAgentStateReader(container.sessions).get_run_state(
        user_id=user_id, run_id=run_id
    )
    if run_state is None:
        raise EvalStateError("agent_run_state_missing")
    steps = await container.trace_reader.list_steps(user_id=user_id, run_id=run_id)
    return EvalTrace(steps, run_status=AgentRunStatus(run_state.status))


async def _execute_real_agent(
    case: EvalCase,
    container: AppContainer,
    clock: EvalClock,
    refs: EvalFixtureRefs,
) -> tuple[list[EvalTurnResult], list[GradeResult]]:
    """Tool / Coaching：真实 LLM 走完整 ChatService 链路，按最后一轮评分。"""
    executions = await _run_turns(
        container=container, clock=clock, user_id=refs.user_id, turns=case_turns(case)
    )
    await drain_durable_tasks(container)
    last = executions[-1]
    if case.suite == "tool":
        graders = grade_tool_expectation(case.expectation, last.trace)
    else:
        graders = await _grade_coaching(case, container, refs, last)
    return [_turn_result(item) for item in executions], graders


async def _grade_coaching(
    case: EvalCase,
    container: AppContainer,
    refs: EvalFixtureRefs,
    last: _TurnExecution,
) -> list[GradeResult]:
    """读取 Coaching Domain State 并按 source identity 关联评分。"""
    plan_id = refs.ids.get("plan_id")
    snapshot_id = refs.ids.get("state_snapshot_id")
    if plan_id is None:
        raise EvalConfigError("coaching_fixture_missing_plan_id")
    reader = EvalCoachingStateReader(container.sessions)
    plan_version = await reader.get_plan_version(user_id=refs.user_id, plan_id=plan_id)
    if plan_version is None:
        raise EvalStateError("coaching_fixture_plan_missing")
    state_version = 0
    if snapshot_id is not None:
        version = await reader.get_state_snapshot_version(
            user_id=refs.user_id, snapshot_id=snapshot_id
        )
        if version is None:
            raise EvalStateError("coaching_fixture_state_missing")
        state_version = version
    return grade_coaching_decision(
        case.expectation,
        plan_changes=await reader.list_plan_changes(user_id=refs.user_id),
        active_plan=await reader.get_active_plan(user_id=refs.user_id),
        fixture_plan_id=plan_id,
        fixture_plan_version=plan_version,
        fixture_state_version=state_version,
        turn_id=last.turn_id,
        run_id=last.run_id,
    )


async def _execute_memory_retrieval(
    case: EvalCase,
    container: AppContainer,
    refs: EvalFixtureRefs,
) -> tuple[list[EvalTurnResult], list[GradeResult]]:
    """Memory Retrieval：直接调用正式 Retrieval Service 评分，不进入 Reasoner。"""
    result = await container.memory_retrieval_service.retrieve(
        user_id=refs.user_id,
        query=case.query,
        as_of=case.as_of,
        semantic_limit=case.semantic_limit,
        episode_limit=case.episode_limit,
    )
    graders = grade_memory_retrieval(case.expectation, result, alias_ids=refs.ids)
    return [], graders


async def _execute_memory_lifecycle(
    case: EvalCase,
    container: AppContainer,
    clock: EvalClock,
    refs: EvalFixtureRefs,
) -> tuple[list[EvalTurnResult], list[GradeResult]]:
    """Memory Lifecycle：纠正 turns → 正式 Projection → 新 Thread 检索验证。"""
    executions = await _run_turns(
        container=container, clock=clock, user_id=refs.user_id, turns=case_turns(case)
    )
    await drain_durable_tasks(container)
    # 纠正轮已投影完成：此时解析 alias 并校验，先于检索轮执行。
    spec = FIXTURES[case.fixture]
    if spec.resolve_ids is None:
        raise EvalConfigError("memory_lifecycle_fixture_missing_resolver")
    resolved = await spec.resolve_ids(container, refs.user_id)
    refs = EvalFixtureRefs(user_id=refs.user_id, ids={**refs.ids, **resolved})
    # 新 Thread（thread_id=None）检索：防止 recent conversation 替 Memory 答对。
    clock.advance_to(case.retrieval_as_of)
    started = time.perf_counter()
    retrieval = await container.chat_service.send_message(
        request_context=RequestContext(
            user_id=refs.user_id,
            request_id=uuid4(),
            trace_id=uuid4(),
            timestamp=case.retrieval_as_of,
        ),
        thread_id=None,
        content=case.retrieval_query,
    )
    retrieval_duration = int((time.perf_counter() - started) * 1000)
    retrieval_trace = await _load_trace(container, refs.user_id, retrieval.run_id)
    await drain_durable_tasks(container)
    memories = await EvalMemoryStateReader(container.sessions).list_semantic_memories(
        user_id=refs.user_id
    )
    graders = grade_memory_conflict(
        case.expectation,
        memories=memories,
        context_manifest=retrieval_trace.context_manifest,
        alias_ids=refs.ids,
    )
    turns = [_turn_result(item) for item in executions]
    turns.append(
        EvalTurnResult(
            thread_id=str(retrieval.thread_id),
            turn_id=str(retrieval.turn_id),
            run_id=str(retrieval.run_id),
            input=case.retrieval_query,
            timestamp=case.retrieval_as_of.isoformat(),
            context_manifest=retrieval_trace.context_manifest,
            run_steps=_steps_dict(retrieval_trace),
            final_answer=retrieval_trace.final_answer,
            duration_ms=retrieval_duration,
        )
    )
    return turns, graders


async def _execute_context_injection(
    case: EvalCase,
    container: AppContainer,
    clock: EvalClock,
    refs: EvalFixtureRefs,
) -> tuple[list[EvalTurnResult], list[GradeResult]]:
    """Context Injection：评分目标是 CONTEXT RunStep，不评价模型回复。"""
    executions = await _run_turns(
        container=container, clock=clock, user_id=refs.user_id, turns=case_turns(case)
    )
    await drain_durable_tasks(container)
    graders = grade_context_injection(
        case.expectation,
        context_manifest=executions[-1].trace.context_manifest,
        alias_ids=refs.ids,
    )
    return [_turn_result(item) for item in executions], graders


def _turn_result(execution: _TurnExecution) -> EvalTurnResult:
    """单轮执行 → 报告快照（保留完整轨迹与上下文清单）。"""
    return EvalTurnResult(
        thread_id=str(execution.thread_id),
        turn_id=str(execution.turn_id),
        run_id=str(execution.run_id),
        input=execution.turn_input,
        timestamp=execution.timestamp.isoformat(),
        context_manifest=execution.trace.context_manifest,
        run_steps=_steps_dict(execution.trace),
        final_answer=execution.trace.final_answer,
        duration_ms=execution.duration_ms,
    )


def _steps_dict(trace: EvalTrace) -> list[dict]:
    """RunStep → JSON 结构（保存全部合成场景轨迹）。"""
    return [
        json_ready(
            {
                "index": step.index,
                "kind": step.kind.value,
                "call_id": step.call_id,
                "input_data": step.input_data,
                "output_data": step.output_data,
                "started_at": step.started_at.isoformat(),
                "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            }
        )
        for step in trace.steps
    ]


def _git_info() -> tuple[str, bool]:
    """读取 git SHA 与 dirty flag；无法读取立即失败，不写 unknown。"""

    def _run(args: list[str]) -> str:
        result = subprocess.run(  # noqa: PLW1510 - 手动检查 returncode 以给出稳定错误码
            ["git", *args], cwd=_BACKEND_ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise EvalEnvironmentError(f"git_command_failed: git {' '.join(args)}")
        return result.stdout.strip()

    sha = _run(["rev-parse", "HEAD"])
    dirty = bool(_run(["status", "--porcelain"]))
    return sha, dirty


def _prompt_version() -> str:
    from app.agent.context.assembler import PROMPT_VERSION

    return PROMPT_VERSION


def _memory_policy_version() -> str:
    from app.memory.application.retrieval_service import POLICY_VERSION

    return POLICY_VERSION
