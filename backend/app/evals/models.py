"""Eval Case 合同：严格 Pydantic Schema（extra=forbid）与按执行方式的 discriminated union。

Case 按 execution mode 分为四类，不使用包含大量可空字段的万能 Expectation；
未知字段、未知版本、无时区时间在加载阶段一律 fail fast。
"""

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# Case / Result / JSON Artifact 的统一 schema 版本；不识别的版本必须 fail fast。
EVAL_CASE_SCHEMA_VERSION = "phase6.v1"
EVAL_REPORT_SCHEMA_VERSION = "phase6.v1"

SuiteName = Literal["tool", "memory", "coaching"]
ExecutionMode = Literal[
    "real_agent", "memory_retrieval", "memory_lifecycle", "context_injection"
]

# 与生产检索上限保持一致：Case 请求条数不允许突破生产策略。
PRODUCTION_SEMANTIC_LIMIT = 8
PRODUCTION_EPISODE_LIMIT = 4


class _StrictModel(BaseModel):
    """全部 Eval 模型的基类：未知字段一律拒绝。"""

    model_config = ConfigDict(extra="forbid")


class CaseTurn(_StrictModel):
    """Agent Case 的单轮用户输入；不提供伪造 assistant/system 的 role 字段。"""

    input: str = Field(min_length=1)  # 本轮用户输入原文
    timestamp: AwareDatetime  # 本轮业务时间（必须带时区）


class ToolExpectation(_StrictModel):
    """Tool 行为预期：区分“尝试调用”与“执行成功”。"""

    required_successful_tools: list[str] = Field(default_factory=list)  # 必须执行成功的工具
    required_discoveries: list[str] = Field(default_factory=list)  # 必须被发现并成功执行的工具
    forbidden_tool_attempts: list[str] = Field(default_factory=list)  # 只要尝试即失败的工具
    max_tool_attempts: int | None = None  # 全部 tool_call（含失败与 search）数量上限


class CoachingExpectation(_StrictModel):
    """Coaching 决策预期：正例要求创建 pending 提案，负例要求不创建。"""

    must_create_plan_change: bool  # True=必须创建；False=禁止创建


class MemoryRetrievalExpectation(_StrictModel):
    """检索预期：required / forbidden 记忆以 fixture alias 表达。"""

    semantic_required: list[str] = Field(default_factory=list)  # 必须进入语义结果的 alias
    semantic_forbidden: list[str] = Field(default_factory=list)  # 禁止进入语义结果的 alias
    episodic_required: list[str] = Field(default_factory=list)  # 必须进入情节结果的 alias
    episodic_forbidden: list[str] = Field(default_factory=list)  # 禁止进入情节结果的 alias


class MemoryConflictExpectation(_StrictModel):
    """生命周期预期：旧记忆被新记忆取代，且新 Thread 检索只召回新知识。"""

    old_alias: str  # 被取代的旧记忆 alias
    new_alias: str  # 取代后的新记忆 alias


class ContextInjectionExpectation(_StrictModel):
    """Context 注入预期：目标记忆 ID 必须出现在 CONTEXT RunStep。"""

    semantic_required: list[str] = Field(default_factory=list)  # 必须注入的语义记忆 alias
    episodic_required: list[str] = Field(default_factory=list)  # 必须注入的情节记忆 alias


class _CaseBase(_StrictModel):
    """四类 Case 的公共字段。"""

    schema_version: Literal["phase6.v1"]  # 未知版本在解析时直接失败
    id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")  # 全局唯一 Case ID
    suite: SuiteName  # 指标归类 suite
    fixture: str = Field(min_length=1)  # Fixture Registry 的白名单键
    tags: list[str] = Field(default_factory=list)


class AgentEvalCase(_CaseBase):
    """真实 Agent Case：从 ChatService 进入，使用真实 ChatService + AgentRuntime + LLM。"""

    execution: Literal["real_agent"]
    turns: list[CaseTurn] = Field(min_length=1)  # 按时间排列的用户轮次
    expectation: ToolExpectation | CoachingExpectation  # 由 suite 进一步约束

    @model_validator(mode="after")
    def _expectation_matches_suite(self) -> "AgentEvalCase":
        expected: type[BaseModel]
        if self.suite == "tool":
            expected = ToolExpectation
        elif self.suite == "coaching":
            expected = CoachingExpectation
        else:
            raise ValueError("real_agent Case 的 suite 只允许 tool / coaching")
        if not isinstance(self.expectation, expected):
            # Pydantic 校验器约定用 ValueError 表达校验失败（TRY004 豁免）。
            raise ValueError(f"suite={self.suite} 的 expectation 必须是 {expected.__name__}")  # noqa: TRY004
        return self


class MemoryRetrievalEvalCase(_CaseBase):
    """Memory Retrieval Case：直接调用正式 Retrieval Service，不混入 Reasoner 噪音。"""

    execution: Literal["memory_retrieval"]
    query: str = Field(min_length=1)  # 检索查询文本
    as_of: AwareDatetime  # 双时间过滤的业务时间基准
    semantic_limit: int = Field(default=PRODUCTION_SEMANTIC_LIMIT, ge=0)  # 不超过生产上限
    episode_limit: int = Field(default=PRODUCTION_EPISODE_LIMIT, ge=0)
    expectation: MemoryRetrievalExpectation

    @model_validator(mode="after")
    def _limits_within_production(self) -> "MemoryRetrievalEvalCase":
        if self.suite != "memory":
            raise ValueError("memory_retrieval Case 的 suite 必须是 memory")
        if self.semantic_limit > PRODUCTION_SEMANTIC_LIMIT:
            raise ValueError(f"semantic_limit 不得超过生产上限 {PRODUCTION_SEMANTIC_LIMIT}")
        if self.episode_limit > PRODUCTION_EPISODE_LIMIT:
            raise ValueError(f"episode_limit 不得超过生产上限 {PRODUCTION_EPISODE_LIMIT}")
        return self


class MemoryLifecycleEvalCase(_CaseBase):
    """Memory Lifecycle Case：确定性 Extractor + 正式 Projection + 新 Thread 检索验证。"""

    execution: Literal["memory_lifecycle"]
    turns: list[CaseTurn] = Field(min_length=1)  # 按时间排列的纠正轮次
    retrieval_query: str = Field(min_length=1)  # 新 Thread 的检索查询
    retrieval_as_of: AwareDatetime  # 检索业务时间（必须晚于全部纠正轮）
    expectation: MemoryConflictExpectation

    @model_validator(mode="after")
    def _suite_is_memory(self) -> "MemoryLifecycleEvalCase":
        if self.suite != "memory":
            raise ValueError("memory_lifecycle Case 的 suite 必须是 memory")
        return self


class ContextInjectionEvalCase(_CaseBase):
    """Context Injection Case：评分目标发生在 Reasoner 调用之前，可用 ScriptedReasoner。"""

    execution: Literal["context_injection"]
    turns: list[CaseTurn] = Field(min_length=1)
    expectation: ContextInjectionExpectation

    @model_validator(mode="after")
    def _suite_is_memory(self) -> "ContextInjectionEvalCase":
        if self.suite != "memory":
            raise ValueError("context_injection Case 的 suite 必须是 memory")
        return self


# 四类 Case 的联合类型：discriminated union 按 execution 字段区分
EvalCase = (
    AgentEvalCase
    | MemoryRetrievalEvalCase
    | MemoryLifecycleEvalCase
    | ContextInjectionEvalCase
)

# 带判别器的联合类型：YAML 解析按 execution 字段直接分派到对应 Case 类。
EvalCaseUnion = Annotated[EvalCase, Field(discriminator="execution")]


def case_id_of(case: EvalCase) -> str:
    """读取 Case 的全局唯一 ID。"""
    return case.id


def case_execution(case: EvalCase) -> ExecutionMode:
    """读取 Case 的执行方式标签（discriminated union 的判别字段）。"""
    return case.execution  # type: ignore[no-any-return]


def case_turns(case: EvalCase) -> list[CaseTurn]:
    """统一读取四类 Case 的用户轮次（Retrieval Case 没有对话轮次，返回空）。"""
    turns = getattr(case, "turns", None)
    return list(turns) if turns is not None else []


def case_expectation(case: EvalCase) -> Any:
    """读取 Case 的 expectation 对象。"""
    return case.expectation
