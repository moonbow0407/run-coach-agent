"""执行轨迹端口：把 AgentRun 的每一步持久化为 RunStep。

用于调试、可观测、评估与审计。轨迹只写不读——正常推理不依赖历史轨迹。
"""

from typing import Protocol
from uuid import UUID

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.observation import Observation


# Protocol（结构化鸭子类型）：只约束方法签名，实现方无需显式继承本类
class AgentTraceRecorder(Protocol):
    """执行轨迹记录接口：Runtime 每推进一步就写入一条对应记录。"""

    # 记录一次推理步：模型给出的 Action 类型（tool_call 或 final）
    async def record_reasoning(
        self,
        *,
        run_id: UUID,
        action_type: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        ...

    # 记录一次工具调用请求（执行前写入）
    async def record_action(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        action: ToolCallAction,
    ) -> None:
        ...

    # 记录工具执行结果（成功与错误 Observation 都记录）
    async def record_observation(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        observation: Observation,
    ) -> None:
        ...

    # 记录最终回答，标志本次 Run 推理结束
    async def record_final(
        self,
        *,
        run_id: UUID,
        action: FinalAction,
    ) -> None:
        ...
