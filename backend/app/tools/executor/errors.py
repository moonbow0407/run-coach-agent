"""Tool 错误码：可恢复 Tool 错误的结构化表达。

五种核心错误（文档 §11）加上 read-only 治理拒绝码。它们都以
Observation 返回，Reasoner 可以继续推理；与 Runtime 不变量破坏
（抛 ToolRuntimeError 使 AgentRun failed）是两条不同通路。
"""

from enum import StrEnum


class ToolErrorCode(StrEnum):
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_NOT_AVAILABLE = "tool_not_available"
    INVALID_ARGUMENTS = "invalid_arguments"
    TOOL_NOT_AUTHORIZED = "tool_not_authorized"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
