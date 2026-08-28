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


class CapabilityError(RunCoachError):
    """Capability 协议或执行失败。未知能力返回 Observation.error，协议违反则抛出本异常。"""


class InfrastructureError(RunCoachError):
    """数据库、LLM 供应商等基础设施失败，归一化后再向上传播。"""
