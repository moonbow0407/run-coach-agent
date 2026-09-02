"""Tool 错误码：可恢复 Tool 错误的结构化表达。

五种核心错误（文档 §11）加上 read-only 治理拒绝码。它们都以
Observation 返回，Reasoner 可以继续推理；与 Runtime 不变量破坏
（抛 ToolRuntimeError 使 AgentRun failed）是两条不同通路。
"""

from enum import StrEnum


class ToolErrorCode(StrEnum):
    """可恢复 Tool 错误码：以 Observation 形式返回，Reasoner 可据此继续推理。"""

    TOOL_NOT_FOUND = "tool_not_found"  # Registry 中不存在该工具
    TOOL_NOT_AVAILABLE = "tool_not_available"  # 工具存在但当前会话不可见
    INVALID_ARGUMENTS = "invalid_arguments"  # 参数校验失败
    TOOL_NOT_AUTHORIZED = "tool_not_authorized"  # 风险等级未获模型执行授权
    TOOL_TIMEOUT = "tool_timeout"  # 执行超过定义的超时上限
    TOOL_EXECUTION_FAILED = "tool_execution_failed"  # 执行期应用错误或未知异常
