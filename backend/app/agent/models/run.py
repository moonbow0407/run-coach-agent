"""AgentRun 与 RunStep：一次 Agent 执行过程及其执行轨迹。

AgentRun 记录“这次执行跑没跑完、结果如何”；
RunStep 记录“每一步做了什么”（推理 / 工具调用 / 观察 / 最终回答），
用于调试、可观测、评估与审计，不是 Runtime 的工作记忆。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStepKind(StrEnum):
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    FINAL = "final"


@dataclass(frozen=True)
class AgentRun:
    """一次 Agent 执行。与 Turn 一一对应：Turn 是对话视角，Run 是执行视角。"""

    id: UUID
    turn_id: UUID
    user_id: UUID
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RunStep:
    """持久化 Execution Trace。不能被当作 AgentRuntime 的工作状态。"""

    id: UUID
    run_id: UUID
    index: int
    kind: RunStepKind
    call_id: UUID | None
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
