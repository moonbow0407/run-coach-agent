from dataclasses import dataclass

from app.agent.context.bundle import ContextBundle
from app.agent.reasoning.state import ReasoningState


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[ModelMessage, ...]
    json_object: bool = True


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str
    usage: dict[str, int] | None = None


@dataclass
class ReasoningContext:
    context_bundle: ContextBundle
    state: ReasoningState
