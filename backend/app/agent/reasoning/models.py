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


# frozen=True：不可变数据类，消息序列组装后不可修改
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

    tool: str  # 工具名
    arguments: dict[str, Any]  # 模型给出的 JSON 参数
    model_call_id: str


@dataclass(frozen=True)
class ToolResultMessage:
    """一次工具调用的结果回传。content 为序列化后的 Observation。"""

    model_call_id: str  # 对应工具调用的协议 ID，用于结果配对
    content: str  # 序列化后的 Observation JSON


# 五类消息的合集类型：一次模型请求的消息序列由它们按序组成
ModelMessage = (
    SystemMessage | UserMessage | AssistantMessage | AssistantToolCall | ToolResultMessage
)


@dataclass(frozen=True)
class ModelToolDefinition:
    """传给模型的 native tool 定义。parameters_schema 来自 Tool 参数模型。"""

    name: str  # 工具名，模型通过它指定要调用的工具
    description: str  # 工具用途说明，帮助模型判断何时调用
    parameters_schema: dict[str, Any]  # 参数 JSON Schema，约束 arguments 的结构


@dataclass(frozen=True)
class ModelRequest:
    """一次模型调用请求：消息序列 + 每轮动态可见的 Tool 定义。"""

    messages: tuple[ModelMessage, ...]  # 按序排列的 native 消息序列
    tools: tuple[ModelToolDefinition, ...] = ()  # 本轮可见的 Tool 定义


@dataclass(frozen=True)
class ModelToolCall:
    """模型返回的 native tool call。arguments 已由 Provider 解析为 JSON 对象。"""

    model_call_id: str  # 供应商返回的协议 ID
    tool: str  # 模型选择调用的工具名
    arguments: dict[str, Any]  # 模型给出的调用参数


@dataclass(frozen=True)
class ModelResponse:
    """模型返回：文本与 native tool call（可能同时出现，附带文本不构成回答）。"""

    text: str  # 模型文本输出（可能为空）
    model: str  # 实际使用的模型标识
    tool_calls: tuple[ModelToolCall, ...] = ()  # 模型发起的工具调用
    usage: dict[str, int] | None = None  # token 用量统计（可选）


@dataclass
class ReasoningContext:
    """每轮推理的输入：稳定 ContextBundle + Run 内工作状态 + 当前可见 Tool。

    visible_tools 由 Resolver 每轮重新计算，ContextBundle 不再携带
    任何 Tool 定义。
    """

    context_bundle: ContextBundle  # 装配好的上下文，整个 Run 内不变
    state: ReasoningState  # Run 内已发生的工具调用与结果
    visible_tools: list[VisibleTool]  # 本轮可见 Tool，每轮可能变化
