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
from app.coaching.application.training_analysis_service import TrainingAnalysisService
from app.coaching.application.workout_service import WorkoutQueryService
from app.common.clock import Clock, SystemClock
from app.common.errors import InfrastructureError, ReasonerError
from app.infrastructure.config import Settings
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
from app.infrastructure.database.session import create_engine, create_session_factory
from app.infrastructure.lifecycle.memory_projection_listener import (
    MemoryProjectionLifecycleListener,
)
from app.infrastructure.lifecycle.plan_change_listener import PlanChangeLifecycleListener
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
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    lifecycle: LifecycleDispatcher
    conversation_store: SqlAlchemyConversationStore
    conversation_reader: SqlAlchemyConversationReader
    chat_service: ChatService
    reasoner: Reasoner
    tool_runtime: ToolRuntime
    tool_registry: ToolRegistry
    goal_service: GoalQueryService
    plan_service: PlanQueryService
    athlete_service: AthleteStateQueryService
    workout_service: WorkoutQueryService
    athlete_recompute_service: AthleteStateRecomputeService
    plan_adaptation_service: PlanAdaptationService
    training_analysis_service: TrainingAnalysisService
    semantic_memory_projection_service: SemanticMemoryProjectionService
    episode_projection_service: EpisodeProjectionService
    memory_retrieval_service: MemoryRetrievalService
    memory_lifecycle_service: MemoryLifecycleService


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
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url, poolclass=poolclass)
    sessions = create_session_factory(engine)
    lifecycle = LifecycleDispatcher()

    workout_repo = SqlAlchemyWorkoutRepository(sessions)
    plan_repo = SqlAlchemyPlanRepository(sessions)
    athlete_repo = SqlAlchemyAthleteStateRepository(sessions)
    plan_change_repo = SqlAlchemyPlanChangeRepository(sessions)
    activation_store = SqlAlchemyPlanActivationStore(sessions)
    workout_service = WorkoutQueryService(workout_repo, clock)
    goal_service = GoalQueryService(SqlAlchemyGoalRepository(sessions))
    plan_service = PlanQueryService(plan_repo)
    athlete_service = AthleteStateQueryService(athlete_repo)
    analysis_service = TrainingAnalysisService(workout_repo, plan_repo)
    athlete_recompute_service = AthleteStateRecomputeService(
        analysis=analysis_service,
        workouts=workout_repo,
        snapshots=athlete_repo,
        clock=clock,
    )
    plan_adaptation_service = PlanAdaptationService(
        plans=plan_repo,
        snapshots=athlete_repo,
        changes=plan_change_repo,
        activation=activation_store,
        clock=clock,
    )
    lifecycle.subscribe(PlanChangeLifecycleListener(plan_adaptation_service))

    conversation_store = SqlAlchemyConversationStore(sessions, clock)
    conversation_reader = SqlAlchemyConversationReader(sessions)
    trace_recorder = SqlAlchemyAgentTraceRecorder(sessions, clock)

    if settings.memory_embedding_dimensions != 1536:
        raise InfrastructureError("memory_embedding_dimensions_must_be_1536")
    memory_client: AsyncOpenAI | None = None
    if settings.llm_api_key:
        if not settings.llm_base_url or not settings.llm_model:
            raise ReasonerError("配置 LLM_API_KEY 时必须同时配置 LLM_BASE_URL 与 LLM_MODEL")
        memory_client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    if embedding_provider is None:
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
    lifecycle.subscribe(
        MemoryProjectionLifecycleListener(
            semantic_projection_service,
            settings.memory_projector_version,
        )
    )

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
            reasoner = _MissingLLMReasoner()
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
        athlete_recompute_service=athlete_recompute_service,
        plan_adaptation_service=plan_adaptation_service,
        training_analysis_service=analysis_service,
        semantic_memory_projection_service=semantic_projection_service,
        episode_projection_service=episode_projection_service,
        memory_retrieval_service=memory_retrieval_service,
        memory_lifecycle_service=memory_lifecycle_service,
    )


class _MissingLLMReasoner:
    async def reason(self, context: object) -> object:
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
