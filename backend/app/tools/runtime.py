"""ToolRuntime 外观：AgentRuntime 访问 Tool 能力的唯一稳定入口。

AgentRuntime 只通过本类创建会话、解析当前可见 Tool 并执行
ToolCallAction；Registry / Search / Resolver / Executor 的组合细节
不泄漏进 Agent Core。
"""

from uuid import UUID

from app.agent.models.action import ToolCallAction
from app.agent.models.observation import Observation
from app.tools.context import ToolExecutionContext
from app.tools.executor.executor import ToolExecutor
from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.resolver import ToolResolver, VisibleTool
from app.tools.resolver.session import ToolSession


class ToolRuntime:
    """组合 Registry/Resolver/Executor 的门面，对 Agent Core 暴露稳定操作。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        resolver: ToolResolver,
        executor: ToolExecutor,
    ) -> None:
        self._registry = registry  # 工具存在性的唯一事实来源
        self._resolver = resolver  # 每轮可见集合计算
        self._executor = executor  # 统一治理与错误归一化

    def create_session(self, *, run_id: UUID) -> ToolSession:
        """每个 AgentRun 创建独立会话；Run 结束后直接销毁，不跨 Turn 复用。"""
        return ToolSession(run_id=run_id, registry=self._registry)

    def visible_tools(self, session: ToolSession) -> list[VisibleTool]:
        """每轮重新计算当前可见 Tool（Resolver 语义）。"""
        return self._resolver.visible_tools(session)

    async def execute_tool_call(
        self,
        *,
        session: ToolSession,
        action: ToolCallAction,
        context: ToolExecutionContext,
    ) -> Observation:
        """执行一次 ToolCallAction，统一治理与错误归一化在 Executor 内完成。"""
        return await self._executor.execute(action=action, session=session, context=context)
