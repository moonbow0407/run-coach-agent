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
    RUNNING = "running"  # 推理运行进行中
    COMPLETED = "completed"  # 正常完成并产出最终回答
    FAILED = "failed"  # 执行失败
    CANCELLED = "cancelled"  # 被取消


class RunStepKind(StrEnum):
    REASONING = "reasoning"  # 一次推理：模型决定下一步动作
    TOOL_CALL = "tool_call"  # 发起一次工具调用
    OBSERVATION = "observation"  # 工具返回结果
    FINAL = "final"  # 产出给用户的最终回答


# frozen=True：不可变数据类，Run / RunStep 落库后即成历史记录，不允许修改
@dataclass(frozen=True)
class AgentRun:
    """一次 Agent 执行。与 Turn 一一对应：Turn 是对话视角，Run 是执行视角。"""

    id: UUID
    turn_id: UUID  # 对应的对话轮次（Turn 看对话，Run 看执行）
    user_id: UUID  # 归属用户
    status: AgentRunStatus  # 执行状态
    started_at: datetime  # 开始时间
    completed_at: datetime | None  # 结束时间，仅终态后有值


@dataclass(frozen=True)
class RunStep:
    """持久化 Execution Trace。不能被当作 AgentRuntime 的工作状态。"""

    id: UUID
    run_id: UUID  # 所属 AgentRun
    index: int  # 步骤序号，标识执行顺序
    kind: RunStepKind  # 步骤类型
    call_id: UUID | None  # 工具调用内部 ID（仅工具相关步骤有值）
    input_data: dict[str, Any] | None  # 该步输入快照
    output_data: dict[str, Any] | None  # 该步输出快照
    started_at: datetime  # 开始时间
    completed_at: datetime | None  # 结束时间，进行中的步骤为 None
