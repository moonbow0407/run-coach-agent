"""AgentRun 检查点端口：写入 / 读取最新可恢复快照。"""

from typing import Protocol
from uuid import UUID

from app.agent.models.checkpoint import AgentRunCheckpoint


class AgentCheckpointStore(Protocol):
    """检查点存储：每次成功 Observation 后落一条；续跑读最新一条。"""

    async def save(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint: ...

    async def get_latest(self, *, user_id: UUID, run_id: UUID) -> AgentRunCheckpoint | None: ...
