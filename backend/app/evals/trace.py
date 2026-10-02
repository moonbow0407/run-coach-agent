"""EvalTrace：生产 RunStep 的只读 Adapter，不是新 Trace 模型。

从 AgentTraceReader 读取的领域 RunStep 重建工具调用轨迹；初始化时执行
结构不变量校验（顺序、配对、终态），任何损坏都抛 EvalTraceError，
由 Runner 归一化为 ERROR，绝不交给行为 Grader 猜测。
"""

import itertools
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.agent.models.run import AgentRunStatus, RunStep, RunStepKind
from app.evals.errors import EvalTraceError


@dataclass(frozen=True)
class AttemptedToolCall:
    """一次工具调用尝试（执行前写入的 tool_call 步骤）。"""

    call_id: UUID  # Runtime 生成的内部调用 ID
    tool: str  # 工具名
    arguments: dict[str, Any]  # 模型提供的业务参数
    model_call_id: str  # 模型协议 ID


@dataclass(frozen=True)
class ToolObservation:
    """一次工具执行结果（success / error 都记录）。"""

    call_id: UUID  # 与触发调用的内部 call_id 一致
    tool: str  # 来源工具名
    status: str  # success / error
    data: Any  # 成功时的返回数据
    error_code: str | None  # 失败时的结构化错误码
    error: str | None  # 失败时的安全错误说明


class EvalTrace:
    """一次 AgentRun 的只读轨迹视图：Context / Tool 配对 / search 命中 / 最终回答。"""

    def __init__(
        self,
        steps: tuple[RunStep, ...],
        *,
        run_status: AgentRunStatus,
    ) -> None:
        self._steps = steps
        self._run_status = run_status
        self._validate()
        self._context_manifest: dict[str, Any] | None = None
        self._attempted: list[AttemptedToolCall] = []
        self._observations: dict[UUID, ToolObservation] = {}
        self._final: str | None = None
        for step in steps:
            if step.kind is RunStepKind.CONTEXT:
                self._context_manifest = dict(step.input_data or {})
            elif step.kind is RunStepKind.TOOL_CALL:
                payload = step.input_data or {}
                self._attempted.append(
                    AttemptedToolCall(
                        call_id=step.call_id,
                        tool=str(payload["tool"]),
                        arguments=dict(payload.get("arguments") or {}),
                        model_call_id=str(payload["model_call_id"]),
                    )
                )
            elif step.kind is RunStepKind.OBSERVATION:
                payload = dict(step.output_data or {})
                self._observations[step.call_id] = ToolObservation(
                    call_id=step.call_id,
                    tool=str(payload.get("source")),
                    status=str(payload.get("status")),
                    data=payload.get("data"),
                    error_code=payload.get("error_code"),
                    error=payload.get("error"),
                )
            elif step.kind is RunStepKind.FINAL:
                self._final = str((step.output_data or {}).get("content"))

    # ---- 结构不变量：损坏即抛 EvalTraceError，不进入评分 ----

    def _validate(self) -> None:
        indexes = [step.index for step in self._steps]
        # index 必须严格递增且唯一，否则轨迹顺序不可信。
        if any(b <= a for a, b in itertools.pairwise(indexes)):
            raise EvalTraceError("run_step_index_not_strictly_increasing")
        kinds = [step.kind for step in self._steps]
        if kinds.count(RunStepKind.CONTEXT) > 1:
            raise EvalTraceError("multiple_context_steps")
        if kinds.count(RunStepKind.FINAL) > 1:
            raise EvalTraceError("multiple_final_steps")
        attempted = {
            step.call_id for step in self._steps if step.kind is RunStepKind.TOOL_CALL
        }
        observed: set[UUID] = set()
        for step in self._steps:
            if step.kind is not RunStepKind.OBSERVATION:
                continue
            # 每个 observation 都必须能配到一条 tool_call。
            if step.call_id not in attempted:
                raise EvalTraceError("observation_without_tool_call")
            # 同一 call_id 只允许一条 observation，重复说明轨迹损坏。
            if step.call_id in observed:
                raise EvalTraceError("duplicate_observation_for_call")
            observed.add(step.call_id)
            call_step = next(
                s
                for s in self._steps
                if s.kind is RunStepKind.TOOL_CALL and s.call_id == step.call_id
            )
            observation = dict(step.output_data or {})
            action = dict(call_step.input_data or {})
            # call_id 与 model_call_id 双向一致：任何不一致都说明轨迹被破坏。
            if observation.get("model_call_id") != action.get("model_call_id"):
                raise EvalTraceError("model_call_id_pairing_mismatch")
        has_final = RunStepKind.FINAL in kinds
        if self._run_status is AgentRunStatus.COMPLETED and not has_final:
            raise EvalTraceError("completed_run_missing_final")
        if self._run_status in (AgentRunStatus.FAILED, AgentRunStatus.CANCELLED) and has_final:
            raise EvalTraceError("terminal_failed_run_has_final")

    # ---- 只读视图 ----

    @property
    def steps(self) -> tuple[RunStep, ...]:
        """原始领域 RunStep（按 index 升序）。"""
        return self._steps

    @property
    def run_status(self) -> AgentRunStatus:
        """本次 AgentRun 的终态。"""
        return self._run_status

    @property
    def context_manifest(self) -> dict[str, Any] | None:
        """CONTEXT RunStep 记录的上下文清单（无 context 步骤时为 None）。"""
        return self._context_manifest

    @property
    def attempted_tool_calls(self) -> tuple[AttemptedToolCall, ...]:
        """全部工具调用尝试（含 search_tools 与失败尝试，按轨迹顺序）。"""
        return tuple(self._attempted)

    @property
    def observations_by_call_id(self) -> dict[UUID, ToolObservation]:
        """内部 call_id → 执行结果。"""
        return dict(self._observations)

    @property
    def final_answer(self) -> str | None:
        """最终回答文本；failed / cancelled 的 Run 没有 final。"""
        return self._final

    def successful_tools(self) -> tuple[str, ...]:
        """执行成功（存在 success Observation）的工具名列表，可重复。"""
        return tuple(
            observation.tool
            for observation in self._observations.values()
            if observation.status == "success"
        )

    def failed_tool_names(self) -> tuple[str, ...]:
        """执行失败的工具名列表（与"尝试未执行"区分）。"""
        return tuple(
            observation.tool
            for observation in self._observations.values()
            if observation.status == "error"
        )

    def search_hits(self) -> tuple[str, ...]:
        """全部成功 search_tools Observation 报告的命中工具名（按顺序，可重复）。"""
        hits: list[str] = []
        for observation in self._observations.values():
            if observation.tool != "search_tools" or observation.status != "success":
                continue
            data = observation.data or {}
            hits.extend(str(hit.get("name")) for hit in data.get("hits", []))
        return tuple(hits)

    def search_hit_step_indexes(self, target: str) -> tuple[int, ...]:
        """报告 target 命中的成功 search Observation 的步骤 index（按轨迹顺序）。"""
        indexes: list[int] = []
        for step in self._steps:
            if step.kind is not RunStepKind.OBSERVATION:
                continue
            payload = dict(step.output_data or {})
            if payload.get("source") != "search_tools" or payload.get("status") != "success":
                continue
            data = payload.get("data") or {}
            if any(str(hit.get("name")) == target for hit in data.get("hits", [])):
                indexes.append(step.index)
        return tuple(indexes)

    def success_observation_index(self, tool: str) -> int | None:
        """指定工具首次执行成功的 Observation 步骤 index；未成功返回 None。"""
        for step in self._steps:
            if step.kind is not RunStepKind.OBSERVATION:
                continue
            payload = dict(step.output_data or {})
            if payload.get("source") == tool and payload.get("status") == "success":
                return step.index
        return None
