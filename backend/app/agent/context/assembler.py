"""上下文装配：决定每次推理前给模型看哪些信息。

ContextAssembler 只回答“上下文由什么组成”，不负责“数据怎么取”——
取数逻辑在 providers.py 的三个 Provider 中：

    WorkingContextProvider      当前目标 / 生效计划 / 最新跑者状态（热上下文）
    ConversationContextProvider 本线程中已提交 Turn 的历史消息
    MemoryContextProvider       长期记忆（语义 + 情节），Phase 1 为空

Phase 2 起 Assembler 不再装配 Tool：可见 Tool 由 Tool Runtime 的
Resolver 每轮计算并传入 ReasoningContext。
"""

from app.agent.context.bundle import ContextAssemblyRequest, ContextBundle
from app.agent.context.providers import (
    ConversationContextProvider,
    MemoryContextProvider,
    WorkingContextProvider,
)

SYSTEM_PROMPT = """你是长期跑步训练教练 Agent。

需要根据已提供的跑者状态和当前可见的工具完成当前任务。
当已有信息不足时，主动调用可见工具获取真实训练证据；可用工具不足时，先用 search_tools 搜索其他可用工具。
不要声称获取了证据中不存在的数据。
训练建议应说明主要判断依据。

不要按固定流程或固定工具顺序执行；根据当前证据决定下一步。
"""


class ContextAssembler:
    def __init__(
        self,
        working_context_provider: WorkingContextProvider,
        conversation_context_provider: ConversationContextProvider,
        memory_context_provider: MemoryContextProvider,
        history_limit: int,
    ) -> None:
        self._working = working_context_provider
        self._conversation = conversation_context_provider
        self._memory = memory_context_provider
        self._history_limit = history_limit

    async def assemble(self, request: ContextAssemblyRequest) -> ContextBundle:
        working = await self._working.load(user_id=request.user_id, as_of=request.timestamp)
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
        return ContextBundle(
            system=SYSTEM_PROMPT.strip(),
            working_context=working,
            recent_messages=recent,
            semantic_memories=semantic,
            episodic_memories=episodic,
            current_input=request.current_input,
        )
