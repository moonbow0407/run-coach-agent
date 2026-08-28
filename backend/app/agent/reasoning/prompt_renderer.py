"""Prompt 渲染：把 ContextBundle + ReasoningState 表达成模型消息序列。

回答的是“这些信息如何呈现给模型”，不做任何数据查询；
也不读取 ORM / RunStep，更不保存隐藏思维链。
"""

import json

from app.agent.context.bundle import ContextBundle
from app.agent.models.action import CapabilityCallAction
from app.agent.models.observation import Observation
from app.agent.reasoning.models import ModelMessage, ModelRequest
from app.agent.reasoning.state import ReasoningState
from app.infrastructure.jsonutil import json_ready


class PromptRenderer:
    """把 ContextBundle + ReasoningState 表达为模型请求。不读取 RunStep。"""

    def render(self, bundle: ContextBundle, state: ReasoningState) -> ModelRequest:
        """生成模型消息序列：系统块 → 历史对话 → 当前输入 → 已发生的交互。"""
        messages: list[ModelMessage] = [
            ModelMessage(role="system", content=_system_block(bundle)),
        ]
        # 历史对话按已提交顺序插入；当前输入只出现一次，且始终排在最后。
        for item in bundle.recent_messages:
            messages.append(ModelMessage(role=item.role, content=item.content))
        messages.append(ModelMessage(role="user", content=bundle.current_input))
        # 非第一轮推理时，把已发生的能力调用与观察作为补充块追加，
        # 模型据此判断证据是否足够、是否需要继续调查。
        if state.interactions:
            messages.append(
                ModelMessage(role="user", content=_interactions_block(state))
            )
        return ModelRequest(messages=tuple(messages), json_object=True)


def _system_block(bundle: ContextBundle) -> str:
    """系统块 = 系统指令 + 热上下文 / 记忆 / 能力清单 + 输出契约。

    输出契约限定模型每轮只能输出两种 JSON 之一：
    capability_call（请求调用能力）或 final（给出最终回答）。
    """
    payload = {
        "working_context": json_ready(bundle.working_context),
        "semantic_memories": json_ready(bundle.semantic_memories),
        "episodic_memories": json_ready(bundle.episodic_memories),
        "capabilities": json_ready(bundle.capabilities),
        "output_contract": {
            "capability_call": {
                "type": "capability_call",
                "capability": "string",
                "arguments": {},
            },
            "final": {"type": "final", "content": "string"},
        },
    }
    return (
        bundle.system
        + "\n\n当前工作上下文与可用能力如下。请只输出一个 JSON 对象，"
        + "不要输出 Markdown 代码块。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _interactions_block(state: ReasoningState) -> str:
    """把本轮已发生的能力调用与观察序列化成提示块。"""
    items: list[dict[str, object]] = []
    for interaction in state.interactions:
        if isinstance(interaction, CapabilityCallAction):
            items.append(
                {
                    "kind": "capability_call",
                    "capability": interaction.capability,
                    "arguments": interaction.arguments,
                }
            )
        elif isinstance(interaction, Observation):
            items.append({"kind": "observation", **interaction.model_dump()})
    return (
        "以下是本轮已经发生的能力调用与观察。请据此决定下一步 Action。\n\n"
        + json.dumps(json_ready(items), ensure_ascii=False, indent=2)
    )
