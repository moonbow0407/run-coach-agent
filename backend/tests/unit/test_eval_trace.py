"""EvalTrace 的结构不变量与只读视图（PHASE 6 §13 / §23.1）。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agent.models.run import AgentRunStatus, RunStep, RunStepKind
from app.evals.errors import EvalTraceError
from app.evals.trace import EvalTrace

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


def _step(
    *,
    index: int,
    kind: RunStepKind,
    call_id=None,
    input_data=None,
    output_data=None,
) -> RunStep:
    """构造最小 RunStep 领域对象。"""
    return RunStep(
        id=uuid4(),
        run_id=uuid4(),
        index=index,
        kind=kind,
        call_id=call_id,
        input_data=input_data,
        output_data=output_data,
        started_at=NOW,
        completed_at=NOW,
    )


def _tool_run(
    *,
    tool: str,
    model_call_id: str,
    arguments: dict | None = None,
    status: str = "success",
    data=None,
    error_code: str | None = None,
    start_index: int = 1,
) -> list[RunStep]:
    """构造一对 tool_call + observation RunStep。"""
    call_id = uuid4()
    return [
        _step(
            index=start_index,
            kind=RunStepKind.TOOL_CALL,
            call_id=call_id,
            input_data={"tool": tool, "arguments": arguments or {}, "model_call_id": model_call_id},
        ),
        _step(
            index=start_index + 1,
            kind=RunStepKind.OBSERVATION,
            call_id=call_id,
            output_data={
                "source": tool,
                "status": status,
                "data": data,
                "error_code": error_code,
                "model_call_id": model_call_id,
            },
        ),
    ]


def test_full_trace_rebuilds_context_tools_and_final() -> None:
    """完整轨迹：context → tool_call → observation → reasoning → final 可重建。"""
    steps = [
        _step(index=1, kind=RunStepKind.CONTEXT, input_data={"goal_id": "g", "semantic_memory_ids": []}),
        *_tool_run(tool="search_tools", model_call_id="m1", start_index=2),
        *_tool_run(tool="get_recent_workouts", model_call_id="m2", start_index=4),
        _step(index=6, kind=RunStepKind.REASONING, output_data={"action_type": "final"}),
        _step(index=7, kind=RunStepKind.FINAL, output_data={"content": "完成"}),
    ]
    trace = EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)
    assert trace.context_manifest == {"goal_id": "g", "semantic_memory_ids": []}
    assert [call.tool for call in trace.attempted_tool_calls] == [
        "search_tools",
        "get_recent_workouts",
    ]
    assert set(trace.successful_tools()) == {"search_tools", "get_recent_workouts"}
    assert trace.search_hits() == ()
    assert trace.final_answer == "完成"


def test_search_hits_and_discovery_ordering_helpers() -> None:
    """search 命中视图与 discovery 顺序判定辅助方法。"""
    steps = [
        *_tool_run(
            tool="search_tools",
            model_call_id="m1",
            data={"query": "负荷", "hits": [{"name": "analyze_training_load"}]},
            start_index=1,
        ),
        *_tool_run(tool="analyze_training_load", model_call_id="m2", start_index=3),
        _step(index=5, kind=RunStepKind.FINAL, output_data={"content": "完成"}),
    ]
    trace = EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)
    assert trace.search_hits() == ("analyze_training_load",)
    assert trace.search_hit_step_indexes("analyze_training_load") == (2,)
    assert trace.success_observation_index("analyze_training_load") == 4
    assert trace.search_hit_step_indexes("missing_tool") == ()


def test_index_must_be_strictly_increasing() -> None:
    """index 非严格递增属轨迹损坏。"""
    steps = [
        _step(index=2, kind=RunStepKind.REASONING, output_data={}),
        _step(index=2, kind=RunStepKind.FINAL, output_data={"content": "x"}),
    ]
    with pytest.raises(EvalTraceError):
        EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)


def test_multiple_final_steps_rejected() -> None:
    """多个 final 步骤属轨迹损坏。"""
    steps = [
        _step(index=1, kind=RunStepKind.FINAL, output_data={"content": "a"}),
        _step(index=2, kind=RunStepKind.FINAL, output_data={"content": "b"}),
    ]
    with pytest.raises(EvalTraceError):
        EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)


def test_observation_without_tool_call_rejected() -> None:
    """observation 没有配对的 tool_call 属轨迹损坏。"""
    orphan = _step(
        index=1,
        kind=RunStepKind.OBSERVATION,
        call_id=uuid4(),
        output_data={"source": "x", "status": "success", "model_call_id": "m"},
    )
    with pytest.raises(EvalTraceError):
        EvalTrace((orphan,), run_status=AgentRunStatus.COMPLETED)


def test_model_call_id_pairing_mismatch_rejected() -> None:
    """observation 与 tool_call 的 model_call_id 不一致属轨迹损坏。"""
    call_id = uuid4()
    steps = [
        _step(
            index=1,
            kind=RunStepKind.TOOL_CALL,
            call_id=call_id,
            input_data={"tool": "t", "arguments": {}, "model_call_id": "m1"},
        ),
        _step(
            index=2,
            kind=RunStepKind.OBSERVATION,
            call_id=call_id,
            output_data={"source": "t", "status": "success", "model_call_id": "m2"},
        ),
    ]
    with pytest.raises(EvalTraceError):
        EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)


def test_completed_run_requires_final_and_failed_run_forbids_final() -> None:
    """completed 必须有 final；failed/cancelled 出现 final 属伪造。"""
    reasoning_only = (_step(index=1, kind=RunStepKind.REASONING, output_data={}),)
    with pytest.raises(EvalTraceError):
        EvalTrace(reasoning_only, run_status=AgentRunStatus.COMPLETED)
    with_final = (
        _step(index=1, kind=RunStepKind.REASONING, output_data={}),
        _step(index=2, kind=RunStepKind.FINAL, output_data={"content": "x"}),
    )
    with pytest.raises(EvalTraceError):
        EvalTrace(with_final, run_status=AgentRunStatus.FAILED)
    # failed 且无 final：合法（Runtime 失败路径）。
    EvalTrace(reasoning_only, run_status=AgentRunStatus.FAILED)


def test_duplicate_observation_for_call_rejected() -> None:
    """同一 call_id 出现两条 observation 属轨迹损坏。"""
    call_id = uuid4()
    steps = [
        _step(
            index=1,
            kind=RunStepKind.TOOL_CALL,
            call_id=call_id,
            input_data={"tool": "t", "arguments": {}, "model_call_id": "m1"},
        ),
        _step(
            index=2,
            kind=RunStepKind.OBSERVATION,
            call_id=call_id,
            output_data={"source": "t", "status": "success", "model_call_id": "m1"},
        ),
        _step(
            index=3,
            kind=RunStepKind.OBSERVATION,
            call_id=call_id,
            output_data={"source": "t", "status": "error", "model_call_id": "m1"},
        ),
    ]
    with pytest.raises(EvalTraceError):
        EvalTrace(tuple(steps), run_status=AgentRunStatus.COMPLETED)
