"""执行轨迹只读端口：供 Eval / 审计按归属用户读取 RunStep。

写入路径（AgentTraceRecorder）与读取路径分离；正常推理不读取历史轨迹，
本端口只服务于调试、评估与审计场景。
"""

from typing import Protocol
from uuid import UUID

from app.agent.models.run import RunStep


# Protocol（结构化鸭子类型）：只约束方法签名，实现方无需显式继承本类
class AgentTraceReader(Protocol):
    """执行轨迹读取接口：必须先校验 run 归属用户，再按 index 返回 RunStep。"""

    async def list_steps(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> tuple[RunStep, ...]:
        """返回指定 Run 的全部轨迹步骤（按 index 升序）。

        run 不存在或不属于该用户统一按 not-found 处理，不泄漏存在性。
        """
        ...
