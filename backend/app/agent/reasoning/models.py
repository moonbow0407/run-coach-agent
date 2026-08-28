"""推理层的请求 / 响应数据结构（provider-neutral native 消息契约）。

消息层明确表达 system text / user text / assistant text / assistant
tool call / tool result 五类消息，不能只用 role+content 覆盖所有形态；
供应商协议的翻译只发生在 LLM Provider Adapter。
"""

from dataclasses import dataclass
from typing import Any

from app.agent.context.bundle import ContextBundle
from app.agent.reasoning.state import ReasoningState
from app.tools.resolver.resolver import VisibleTool


@dataclass(frozen=True)
class SystemMessage:
    """system 文本指令。"""

    content: str


@dataclass(frozen=True)
class UserMessage:
    """用户文本输入。"""

    content: str


@dataclass(frozen=True)
class AssistantMessage:
    """assistant 文本输出（历史 committed 对话中的助手消息）。"""

    content: str


@dataclass(frozen=True)
class AssistantToolCall:
    """assistant 发起的一次工具调用（native tool calling 协议形态）。

    model_call_id 是供应商返回的 opaque 协议 ID，在下一次请求的
    tool result 中原样回传。
    """

    tool: str
    arguments: dict[str, Any]
    model_call_id: str


@dataclass(frozen=True)
class ToolResultMessage:
    """一次工具调用的结果回传。content 为序列化后的 Observation。"""

    model_call_id: str
    content: str


ModelMessage = (
    SystemMessage | UserMessage | AssistantMessage | AssistantToolCall | ToolResultMessage
)


@dataclass(frozen=True)
class ModelToolDefinition:
    """传给模型的 native tool 定义。parameters_schema 来自 Tool 参数模型。"""

    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True)
class ModelRequest:
    """一次模型调用请求：消息序列 + 每轮动态可见的 Tool 定义。"""

    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelToolDefinition, ...] = ()


@dataclass(frozen=True)
class ModelToolCall:
    """模型返回的 native tool call。arguments 已由 Provider 解析为 JSON 对象。"""

    model_call_id: str
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    """模型返回：文本与 native tool call（可能同时出现，附带文本不构成回答）。"""

    text: str
    model: str
    tool_calls: tuple[ModelToolCall, ...] = ()
    usage: dict[str, int] | None = None


@dataclass
class ReasoningContext:
    """每轮推理的输入：稳定 ContextBundle + Run 内工作状态 + 当前可见 Tool。

    visible_tools 由 Resolver 每轮重新计算，ContextBundle 不再携带
    任何 Tool 定义。
    """

    context_bundle: ContextBundle
    state: ReasoningState
    visible_tools: list[VisibleTool]
