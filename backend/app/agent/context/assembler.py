from app.agent.context.bundle import ContextAssemblyRequest, ContextBundle
from app.agent.context.providers import (
    CapabilityContextProvider,
    ConversationContextProvider,
    MemoryContextProvider,
    WorkingContextProvider,
)

SYSTEM_PROMPT = """你是长期跑步训练教练 Agent。

需要根据已提供的跑者状态和工具能力完成当前任务。
当已有信息不足时，可以主动使用可用能力获取证据。
不要声称获取了上下文中不存在的数据。
训练建议应说明主要判断依据。

不要按固定流程或固定工具顺序执行；根据当前证据决定下一步。
"""


class ContextAssembler:
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
        self._history_limit = history_limit

    async def assemble(self, request: ContextAssemblyRequest) -> ContextBundle:
        working = await self._working.load(user_id=request.user_id)
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
