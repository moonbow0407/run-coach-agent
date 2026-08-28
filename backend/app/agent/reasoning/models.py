"""推理层的请求 / 响应数据结构。

这些是与具体模型供应商无关的消息契约，Reasoner 与 LLM Provider 之间
通过它们传递信息，使模型可替换而不影响 Agent Core。
"""

from dataclasses import dataclass

from app.agent.context.bundle import ContextBundle
from app.agent.reasoning.state import ReasoningState


@dataclass(frozen=True)
class ModelMessage:
    """发给模型的一条消息（role 为 system / user / assistant）。"""

    role: str
    content: str


@dataclass(frozen=True)
class ModelRequest:
    """一次模型调用请求。json_object=True 表示要求模型只输出 JSON。"""

    messages: tuple[ModelMessage, ...]
    json_object: bool = True


@dataclass(frozen=True)
class ModelResponse:
    """模型返回的文本与 token 用量。"""

    text: str
    model: str
    usage: dict[str, int] | None = None


@dataclass
class ReasoningContext:
    """每轮推理的输入：装配好的上下文 + 运行中工作状态。"""

    context_bundle: ContextBundle
    state: ReasoningState
