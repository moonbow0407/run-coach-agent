"""执行轨迹端口：把 AgentRun 的每一步持久化为 RunStep。

用于调试、可观测、评估与审计。轨迹只写不读——正常推理不依赖历史轨迹。
"""

from typing import Protocol
from uuid import UUID

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.models.observation import Observation


class AgentTraceRecorder(Protocol):
    async def record_reasoning(
        self,
        *,
        run_id: UUID,
        action_type: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        ...

    async def record_action(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        action: CapabilityCallAction,
    ) -> None:
        ...

    async def record_observation(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        observation: Observation,
    ) -> None:
        ...

    async def record_final(
        self,
        *,
        run_id: UUID,
        action: FinalAction,
    ) -> None:
        ...
