"""应用异常体系。

RunCoachError 是根类型：API 边界只认识这一族错误；
各层按语义抛出子类，基础设施异常在边界处归一化，不上抛内部细节。
"""


class RunCoachError(Exception):
    """应用异常根类型。边界处只向上暴露这一族错误，不泄漏基础设施细节。"""


class DomainError(RunCoachError):
    """违反领域不变量，例如量表越界或非法状态。"""


class ApplicationError(RunCoachError):
    """应用层可预期失败，例如资源不存在或请求不合法。"""


class NotFoundError(ApplicationError):
    pass


class ForbiddenError(ApplicationError):
    pass


class AuthenticationError(ApplicationError):
    pass


class AgentRuntimeError(RunCoachError):
    """AgentRuntime 执行失败。ChatService 据此将 Turn 置为 failed。"""


class TurnCancelled(AgentRuntimeError):
    """当前 AgentRun 被取消。ChatService 据此将 Turn 置为 cancelled，而不是 failed。"""


class ReasonerError(RunCoachError):
    """Reasoner 无法产出合法 Action。"""


class ToolRuntimeError(RunCoachError):
    """Tool Runtime 不变量破坏（Registry 状态损坏、ToolSession 与 AgentRun 不一致、无法建立可信上下文等）。

    与五种可恢复的 Tool 错误 Observation（tool_not_found 等）不同：
    本异常使 AgentRun failed，绝不伪装成 Tool 执行结果。
    """


class InfrastructureError(RunCoachError):
    """数据库、LLM 供应商等基础设施失败，归一化后再向上传播。"""
