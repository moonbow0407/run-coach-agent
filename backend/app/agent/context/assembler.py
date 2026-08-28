"""上下文装配：决定每次推理前给模型看哪些信息。

ContextAssembler 只回答“上下文由什么组成”，不负责“数据怎么取”——
取数逻辑在 providers.py 的四个 Provider 中：

    WorkingContextProvider     当前目标 / 生效计划 / 最新跑者状态（热上下文）
    ConversationContextProvider 本线程中已提交 Turn 的历史消息
    MemoryContextProvider      长期记忆（语义 + 情节），Phase 1 为空
    CapabilityContextProvider  可调用能力清单
"""

from app.agent.context.bundle import ContextAssemblyRequest, ContextBundle
from app.agent.context.providers import (
    CapabilityContextProvider,
    ConversationContextProvider,
    MemoryContextProvider,
    WorkingContextProvider,
)

# 系统指令强调：按证据行事、禁止编造数据、说明判断依据、不固定工具调用顺序。
SYSTEM_PROMPT = """你是长期跑步训练教练 Agent。

需要根据已提供的跑者状态和工具能力完成当前任务。
当已有信息不足时，可以主动使用可用能力获取证据。
不要声称获取了上下文中不存在的数据。
训练建议应说明主要判断依据。

不要按固定流程或固定工具顺序执行；根据当前证据决定下一步。
"""


class ContextAssembler:
    """按固定结构组装 ContextBundle；不直接执行 SQL 或向量检索。"""

    def __init__(
        self,
        working_context_provider: WorkingContextProvider,
        conversation_context_provider: ConversationContextProvider,
        memory_context_provider: MemoryContextProvider,
        capability_context_provider: CapabilityContextProvider,
        history_limit: int,
    ) -> None:
        self._working = working_context_provider
        self._conversation = conversation_context_provider
        self._memory = memory_context_provider
        self._capabilities = capability_context_provider
        # 历史对话条数上限：控制 Prompt 长度，避免无限增长。
        self._history_limit = history_limit

    async def assemble(self, request: ContextAssemblyRequest) -> ContextBundle:
        """并行装载四类上下文数据，合成一份 ContextBundle。"""
        working = await self._working.load(user_id=request.user_id)
        # exclude_turn_id：本轮用户消息已为事务可靠性提前入库，
        # 历史上下文必须排除本轮，保证当前输入在 Prompt 中只出现一次。
        recent = await self._conversation.load(
            user_id=request.user_id,
            thread_id=request.thread_id,
            exclude_turn_id=request.turn_id,
            limit=self._history_limit,
        )
        semantic, episodic = await self._memory.load(
            user_id=request.user_id,
            current_input=request.current_input,
        )
        capabilities = await self._capabilities.load()
        return ContextBundle(
            system=SYSTEM_PROMPT.strip(),
            working_context=working,
            recent_messages=recent,
            semantic_memories=semantic,
            episodic_memories=episodic,
            capabilities=capabilities,
            current_input=request.current_input,
        )
