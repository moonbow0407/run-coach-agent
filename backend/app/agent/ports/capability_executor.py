"""能力执行端口：AgentRuntime 通过它与领域能力解耦。

Runtime 只认识本接口，不关心能力具体怎么实现；
实现方（Phase 1 的 SimpleCapabilityExecutor、Phase 2 的 Tool Runtime）
负责参数校验、授权与错误归一化。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.agent.models.observation import Observation


@dataclass(frozen=True)
class CapabilityExecutionContext:
    """可信运行信息。user_id 只来自这里，不来自模型参数。"""

    user_id: UUID
    run_id: UUID
    turn_id: UUID
    request_id: UUID
    timestamp: datetime


class CapabilityExecutor(Protocol):
    async def execute(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> Observation:
        ...
