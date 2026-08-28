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
        messages: list[ModelMessage] = [
            ModelMessage(role="system", content=_system_block(bundle)),
        ]
        for item in bundle.recent_messages:
            messages.append(ModelMessage(role=item.role, content=item.content))
        messages.append(ModelMessage(role="user", content=bundle.current_input))
        if state.interactions:
            messages.append(
                ModelMessage(role="user", content=_interactions_block(state))
            )
        return ModelRequest(messages=tuple(messages), json_object=True)


def _system_block(bundle: ContextBundle) -> str:
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
