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
