"""应用装配层：把各层的实现对象组装成一张可运行的对象图。

装配时的依赖方向（上层只认识下层接口，接口定义在各模块的 ports 中）：

    API 路由
      -> ChatService            对话编排与事务边界
        -> AgentRuntime         推理循环
          -> ContextAssembler   装配上下文
          -> Reasoner           调用大模型产出 Action（native tool calling）
          -> ToolRuntime        Tool 治理入口（Registry / Search / Resolver / Executor）
            -> Coaching Tools -> coaching 查询服务 -> PostgreSQL 仓储

本模块负责把接口与具体实现（SqlAlchemy / OpenAI 兼容 API）“接线”到一起。
测试可以通过 build_container / create_app 的参数注入替身实现。
Tool 注册在进程启动时由 Provider 确定性完成（System + Coaching 查询 / 分析 / 草案）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import Pool

from app.agent.application.chat_service import ChatService
from app.agent.context.assembler import ContextAssembler
from app.agent.context.providers import (
    DomainWorkingContextProvider,
    SqlConversationContextProvider,
)
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.reasoning.llm_reasoner import LLMReasoner
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.agent.reasoning.reasoner import Reasoner
from app.agent.runtime.agent_runtime import AgentRuntime
from app.api.routes.chat import router as chat_router
from app.api.routes.coaching import router as coaching_router
from app.api.routes.health import router as health_router
from app.api.routes.plan_changes import router as plan_changes_router
from app.coaching.application.athlete_recompute_service import AthleteStateRecomputeService
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_adaptation_service import PlanAdaptationService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.terminal_turn_service import TerminalTurnFinalizationService
from app.coaching.application.training_analysis_service import TrainingAnalysisService
from app.coaching.application.workout_command_service import (
    WorkoutCommandService,
    WorkoutFeedbackCommandService,
)
from app.coaching.application.workout_service import WorkoutQueryService
from app.common.clock import Clock, SystemClock
from app.common.errors import InfrastructureError, ReasonerError
from app.infrastructure.config import Settings
from app.infrastructure.database.repositories.athlete_recompute import (
    SqlAlchemyAthleteStateRecomputeUnitOfWork,
)
from app.infrastructure.database.repositories.coaching import (
    SqlAlchemyAthleteStateRepository,
    SqlAlchemyGoalRepository,
    SqlAlchemyPlanChangeRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyWorkoutRepository,
)
from app.infrastructure.database.repositories.conversation import (
    SqlAlchemyConversationReader,
    SqlAlchemyConversationStore,
)
from app.infrastructure.database.repositories.memory import SqlAlchemyMemoryRepository
from app.infrastructure.database.repositories.memory_evidence import (
    SqlAlchemyEvidenceReader,
)
from app.infrastructure.database.repositories.plan_activation import (
    SqlAlchemyPlanActivationStore,
)
from app.infrastructure.database.repositories.trace import SqlAlchemyAgentTraceRecorder
from app.infrastructure.database.repositories.workout_mutation import (
    SqlAlchemyWorkoutMutationStore,
)
from app.infrastructure.database.session import create_engine, create_session_factory
from app.infrastructure.llm.provider import OpenAICompatibleProvider
from app.infrastructure.logging import configure_logging
from app.infrastructure.memory.embedding import (
    OpenAIEmbeddingProvider,
    UnavailableEmbeddingProvider,
)
from app.infrastructure.memory.episode_detection import CanonicalEpisodeDetector
from app.infrastructure.memory.extraction import (
    OpenAISemanticMemoryExtractor,
    UnavailableSemanticMemoryExtractor,
)
from app.infrastructure.outbox.writer import OutboxWriter
from app.memory.application.episode_projection_service import EpisodeProjectionService
from app.memory.application.lifecycle_service import MemoryLifecycleService
from app.memory.application.retrieval_service import MemoryRetrievalService
from app.memory.application.semantic_projection_service import (
    SemanticMemoryProjectionService,
)
from app.memory.context_provider import RetrievedMemoryContextProvider
from app.memory.ports.embedding import EmbeddingProvider
from app.memory.ports.extractor import EpisodeDetector, SemanticMemoryExtractor
from app.tools.builtin.providers import CoachingToolProvider, SystemToolProvider
from app.tools.executor.executor import ToolExecutor
from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.resolver import ToolResolver
from app.tools.runtime import ToolRuntime
from app.tools.search.keyword_search import KeywordToolSearch


@dataclass
class AppContainer:
    """组合根产出的对象图：应用各层实现按依赖方向接线后的容器。"""

    settings: Settings  # 运行配置
    clock: Clock  # 时钟（可注入假时钟供测试）
    engine: AsyncEngine  # 数据库异步引擎
    sessions: async_sessionmaker[AsyncSession]  # 全局共享的 session 工厂
    lifecycle: LifecycleDispatcher  # Agent 终态事件分发器（进程内事件总线）
    conversation_store: SqlAlchemyConversationStore  # 对话写路径（Turn 生命周期事务）
    conversation_reader: SqlAlchemyConversationReader  # 对话只读查询
    chat_service: ChatService  # 对话编排与事务边界
    reasoner: Reasoner  # 大模型推理器
    tool_runtime: ToolRuntime  # Tool 治理入口（搜索/解析/执行）
    tool_registry: ToolRegistry  # 工具注册表
    goal_service: GoalQueryService  # 目标查询
    plan_service: PlanQueryService  # 计划查询
    athlete_service: AthleteStateQueryService  # 跑者状态查询
    workout_service: WorkoutQueryService  # 训练查询
    workout_command_service: WorkoutCommandService  # 训练写入（含 outbox 事件）
    workout_feedback_command_service: WorkoutFeedbackCommandService  # 训练反馈写入
    athlete_recompute_service: AthleteStateRecomputeService  # 跑者状态重算
    plan_adaptation_service: PlanAdaptationService  # 计划调整（提案生成/确认）
    terminal_turn_finalization_service: TerminalTurnFinalizationService  # Turn 终态收尾（驱动计划适配）
    training_analysis_service: TrainingAnalysisService  # 训练负荷分析
    semantic_memory_projection_service: SemanticMemoryProjectionService  # 语义记忆投影
    episode_projection_service: EpisodeProjectionService  # 情节记忆投影
    memory_retrieval_service: MemoryRetrievalService  # 记忆相似检索
    memory_lifecycle_service: MemoryLifecycleService  # 记忆生命周期（过期/取代）


def build_container(
    settings: Settings,
    *,
    reasoner: Reasoner | None = None,
    clock: Clock | None = None,
    poolclass: type[Pool] | None = None,
    memory_extractor: SemanticMemoryExtractor | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    episode_detector: EpisodeDetector | None = None,
) -> AppContainer:
    """按依赖方向把全部实现装配成 AppContainer；参数可注入测试替身。"""
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url, poolclass=poolclass)
    sessions = create_session_factory(engine)
    lifecycle = LifecycleDispatcher()
    outbox = OutboxWriter()

    workout_repo = SqlAlchemyWorkoutRepository(sessions)
    workout_mutation_store = SqlAlchemyWorkoutMutationStore(sessions, outbox)
    plan_repo = SqlAlchemyPlanRepository(sessions)
    athlete_repo = SqlAlchemyAthleteStateRepository(sessions)
    plan_change_repo = SqlAlchemyPlanChangeRepository(sessions)
    activation_store = SqlAlchemyPlanActivationStore(sessions, outbox)
    workout_service = WorkoutQueryService(workout_repo, clock)
    workout_command_service = WorkoutCommandService(workout_mutation_store, clock)
    workout_feedback_command_service = WorkoutFeedbackCommandService(
        workout_mutation_store, clock
    )
    goal_service = GoalQueryService(SqlAlchemyGoalRepository(sessions))
    plan_service = PlanQueryService(plan_repo)
    athlete_service = AthleteStateQueryService(athlete_repo)
    analysis_service = TrainingAnalysisService(workout_repo, plan_repo)
    athlete_recompute_service = AthleteStateRecomputeService(
        unit_of_work=SqlAlchemyAthleteStateRecomputeUnitOfWork(sessions, outbox),
        clock=clock,
    )
    plan_adaptation_service = PlanAdaptationService(
        plans=plan_repo,
        snapshots=athlete_repo,
        changes=plan_change_repo,
        activation=activation_store,
        clock=clock,
    )

    conversation_store = SqlAlchemyConversationStore(sessions, clock, outbox)
    conversation_reader = SqlAlchemyConversationReader(sessions)
    terminal_turn_finalization_service = TerminalTurnFinalizationService(
        conversations=conversation_reader,
        plan_adaptation=plan_adaptation_service,
    )
    trace_recorder = SqlAlchemyAgentTraceRecorder(sessions, clock)

    if settings.memory_embedding_dimensions != 1536:
        # 维度是 Phase 4 持久化合同：pgvector 列按 1536 建，不允许随意改
        raise InfrastructureError("memory_embedding_dimensions_must_be_1536")
    memory_client: AsyncOpenAI | None = None
    if settings.llm_api_key:
        if not settings.llm_base_url or not settings.llm_model:
            raise ReasonerError("配置 LLM_API_KEY 时必须同时配置 LLM_BASE_URL 与 LLM_MODEL")
        memory_client = AsyncOpenAI(  # 记忆抽取与 embedding 共用同一 OpenAI 客户端
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    if embedding_provider is None:
        # 未注入替身时按配置装配：有客户端用真实现，否则显式失败边界
        embedding_provider = (
            OpenAIEmbeddingProvider(
                client=memory_client,
                model=settings.memory_embedding_model,
                version=settings.memory_embedding_version,
                dimensions=settings.memory_embedding_dimensions,
            )
            if memory_client is not None
            else UnavailableEmbeddingProvider()
        )
    if memory_extractor is None:
        # 同上：LLM 配置齐备才装配真抽取器，否则显式失败
        memory_extractor = (
            OpenAISemanticMemoryExtractor(client=memory_client, model=settings.llm_model)
            if memory_client is not None and settings.llm_model is not None
            else UnavailableSemanticMemoryExtractor()
        )
    episode_detector = episode_detector or CanonicalEpisodeDetector()
    memory_repository = SqlAlchemyMemoryRepository(sessions)
    evidence_reader = SqlAlchemyEvidenceReader(sessions)
    semantic_projection_service = SemanticMemoryProjectionService(
        conversations=conversation_reader,
        evidence_reader=evidence_reader,
        extractor=memory_extractor,
        embedding=embedding_provider,
        repository=memory_repository,
        clock=clock,
    )
    episode_projection_service = EpisodeProjectionService(
        evidence_reader=evidence_reader,
        detector=episode_detector,
        embedding=embedding_provider,
        repository=memory_repository,
        clock=clock,
    )
    memory_retrieval_service = MemoryRetrievalService(
        repository=memory_repository,
        embedding=embedding_provider,
    )
    memory_lifecycle_service = MemoryLifecycleService(memory_repository)

    # Tool Runtime 装配：Search Index 由 Registry 维护生命周期；
    # search_tools 依赖同一份 Resolver，保证过滤口径与每轮可见集合一致。
    search = KeywordToolSearch()
    registry = ToolRegistry(search=search)
    resolver = ToolResolver(registry=registry)
    executor = ToolExecutor(registry=registry, resolver=resolver)
    tool_runtime = ToolRuntime(registry=registry, resolver=resolver, executor=executor)

    # 启动时确定性注册：System（search_tools）+ Coaching（查询 / 分析 / 草案）。
    for provider in (
        SystemToolProvider(search=search, resolver=resolver),
        CoachingToolProvider(
            workout_service=workout_service,
            goal_service=goal_service,
            plan_service=plan_service,
            athlete_service=athlete_service,
            analysis_service=analysis_service,
            plan_adaptation_service=plan_adaptation_service,
        ),
    ):
        for tool in provider.tools():
            registry.register(tool)

    assembler = ContextAssembler(
        working_context_provider=DomainWorkingContextProvider(
            goal_service, plan_service, athlete_service
        ),
        conversation_context_provider=SqlConversationContextProvider(conversation_reader),
        memory_context_provider=RetrievedMemoryContextProvider(memory_retrieval_service),
        history_limit=settings.conversation_history_limit,
    )
    if reasoner is None:
        if not settings.llm_api_key:
            reasoner = _MissingLLMReasoner()  # 未配置 LLM：运行到推理时才显式报错
        else:
            if not settings.llm_base_url or not settings.llm_model:
                raise ReasonerError("启用 LLMReasoner 时必须同时配置 LLM_BASE_URL 与 LLM_MODEL")
            reasoner = LLMReasoner(
                OpenAICompatibleProvider(
                    client=AsyncOpenAI(
                        api_key=settings.llm_api_key,
                        base_url=settings.llm_base_url,
                    ),
                    model=settings.llm_model,
                ),
                PromptRenderer(),
            )

    runtime = AgentRuntime(
        reasoner=reasoner,
        context_assembler=assembler,
        tool_runtime=tool_runtime,
        lifecycle=lifecycle,
        trace_recorder=trace_recorder,
        max_steps=settings.agent_max_steps,
    )
    chat_service = ChatService(conversation_store, runtime, lifecycle)
    return AppContainer(
        settings=settings,
        clock=clock,
        engine=engine,
        sessions=sessions,
        lifecycle=lifecycle,
        conversation_store=conversation_store,
        conversation_reader=conversation_reader,
        chat_service=chat_service,
        reasoner=reasoner,
        tool_runtime=tool_runtime,
        tool_registry=registry,
        goal_service=goal_service,
        plan_service=plan_service,
        athlete_service=athlete_service,
        workout_service=workout_service,
        workout_command_service=workout_command_service,
        workout_feedback_command_service=workout_feedback_command_service,
        athlete_recompute_service=athlete_recompute_service,
        plan_adaptation_service=plan_adaptation_service,
        terminal_turn_finalization_service=terminal_turn_finalization_service,
        training_analysis_service=analysis_service,
        semantic_memory_projection_service=semantic_projection_service,
        episode_projection_service=episode_projection_service,
        memory_retrieval_service=memory_retrieval_service,
        memory_lifecycle_service=memory_lifecycle_service,
    )


class _MissingLLMReasoner:
    """未配置 LLM 时的占位实现：一旦被调用立即报错，不伪造推理结果。"""

    async def reason(self, context: object, on_text_delta: object | None = None) -> object:
        raise ReasonerError("未配置 LLM_API_KEY，无法使用 LLMReasoner")


def create_app(
    settings: Settings | None = None,
    *,
    reasoner: Reasoner | None = None,
    clock: Clock | None = None,
    poolclass: type[Pool] | None = None,
    memory_extractor: SemanticMemoryExtractor | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    episode_detector: EpisodeDetector | None = None,
) -> FastAPI:
    """创建 FastAPI 应用：装配容器、挂载 state 与路由；参数供测试注入替身。"""
    configure_logging()
    settings = settings or Settings()
    container = build_container(
        settings,
        reasoner=reasoner,
        clock=clock,
        poolclass=poolclass,
        memory_extractor=memory_extractor,
        embedding_provider=embedding_provider,
        episode_detector=episode_detector,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 应用关闭时释放数据库连接池
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="Run Coach Agent", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.state.settings = container.settings
    app.state.clock = container.clock
    app.state.engine = container.engine
    app.state.sessions = container.sessions
    app.state.lifecycle = container.lifecycle
    app.state.conversation_store = container.conversation_store
    app.state.conversation_reader = container.conversation_reader
    app.state.chat_service = container.chat_service
    app.state.tool_runtime = container.tool_runtime
    app.state.tool_registry = container.tool_registry
    app.state.goal_service = container.goal_service
    app.state.plan_service = container.plan_service
    app.state.athlete_service = container.athlete_service
    app.state.workout_service = container.workout_service
    app.state.workout_command_service = container.workout_command_service
    app.state.workout_feedback_command_service = container.workout_feedback_command_service
    app.state.athlete_recompute_service = container.athlete_recompute_service
    app.state.plan_adaptation_service = container.plan_adaptation_service
    app.state.training_analysis_service = container.training_analysis_service
    app.state.semantic_memory_projection_service = container.semantic_memory_projection_service
    app.state.episode_projection_service = container.episode_projection_service
    app.state.memory_retrieval_service = container.memory_retrieval_service
    app.state.memory_lifecycle_service = container.memory_lifecycle_service
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(plan_changes_router)
    app.include_router(coaching_router)
    return app
