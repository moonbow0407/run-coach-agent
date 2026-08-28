"""Prompt 渲染：把上下文与运行状态还原为 native 消息序列。

根据 ContextBundle 与 ReasoningState 还原：
user input → assistant tool call → tool result → 后续 assistant tool call
或 assistant final text。system 块只包含教练角色指令、工作上下文与
Memory 接缝，不包含 Tool Schema、输出 JSON Contract 或固定流程；
Tool Schema 由 ReasoningContext.visible_tools 单独传入。
"""

import json
from collections.abc import Sequence

from app.agent.context.bundle import ContextBundle
from app.agent.models.action import ToolCallAction
from app.agent.models.message import MessageRole
from app.agent.models.observation import Observation
from app.agent.reasoning.models import (
    AssistantMessage,
    AssistantToolCall,
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from app.agent.reasoning.state import ReasoningState
from app.common.errors import AgentRuntimeError
from app.infrastructure.jsonutil import json_ready
from app.tools.resolver.resolver import VisibleTool


class PromptRenderer:
    """把 ContextBundle + ReasoningState + 当前可见 Tool 表达为模型请求。不读取 RunStep。"""

    def render(
        self,
        bundle: ContextBundle,
        state: ReasoningState,
        visible_tools: Sequence[VisibleTool],
    ) -> ModelRequest:
        messages: list[ModelMessage] = [SystemMessage(content=_system_block(bundle))]
        for item in bundle.recent_messages:
            if item.role == MessageRole.USER.value:
                messages.append(UserMessage(content=item.content))
            elif item.role == MessageRole.ASSISTANT.value:
                messages.append(AssistantMessage(content=item.content))
            else:
                raise AgentRuntimeError(f"未知历史消息角色: {item.role}")
        messages.append(UserMessage(content=bundle.current_input))

        # Run 内交互还原为 native 协议序列：assistant tool call → tool result → …
        for interaction in state.interactions:
            if isinstance(interaction, ToolCallAction):
                messages.append(
                    AssistantToolCall(
                        tool=interaction.tool,
                        arguments=interaction.arguments,
                        model_call_id=interaction.model_call_id,
                    )
                )
            else:
                messages.append(
                    ToolResultMessage(
                        model_call_id=interaction.model_call_id,
                        content=_observation_content(interaction),
                    )
                )

        return ModelRequest(
            messages=tuple(messages),
            tools=tuple(
                ModelToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters_schema=tool.parameters_schema,
                )
                for tool in visible_tools
            ),
        )


def _system_block(bundle: ContextBundle) -> str:
    payload = {
        "working_context": json_ready(bundle.working_context),
        "semantic_memories": json_ready(bundle.semantic_memories),
        "episodic_memories": json_ready(bundle.episodic_memories),
    }
    return (
        bundle.system
        + "\n\n当前工作上下文如下。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _observation_content(observation: Observation) -> str:
    return json.dumps(json_ready(observation.model_dump()), ensure_ascii=False)
