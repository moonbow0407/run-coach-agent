"""应用装配层：把各层的实现对象组装成一张可运行的对象图。

装配时的依赖方向（上层只认识下层接口，接口定义在各模块的 ports 中）：

    API 路由
      → ChatService            对话编排与事务边界
        → AgentRuntime         推理循环
          → ContextAssembler   装配上下文
          → Reasoner           调用大模型产出 Action
          → CapabilityExecutor 执行领域能力
            → coaching 查询服务 → PostgreSQL 仓储

本模块负责把接口与具体实现（SqlAlchemy / OpenAI 兼容 API）“接线”到一起。
测试可以通过 build_container / create_app 的参数注入替身实现。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import Pool

from app.agent.application.chat_service import ChatService
from app.agent.context.assembler import ContextAssembler
from app.agent.context.providers import (
    DomainWorkingContextProvider,
    NullMemoryContextProvider,
    SqlConversationContextProvider,
    StaticCapabilityContextProvider,
)
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.reasoning.llm_reasoner import LLMReasoner
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.agent.reasoning.reasoner import Reasoner
from app.agent.runtime.agent_runtime import AgentRuntime
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.coaching.application.athlete_service import AthleteStateQueryService
from app.coaching.application.goal_service import GoalQueryService
from app.coaching.application.plan_service import PlanQueryService
from app.coaching.application.workout_service import WorkoutQueryService
from app.common.clock import Clock, SystemClock
from app.common.errors import ReasonerError
from app.infrastructure.capabilities.simple_executor import SimpleCapabilityExecutor
from app.infrastructure.config import Settings
from app.infrastructure.database.repositories.coaching import (
    SqlAlchemyAthleteStateRepository,
    SqlAlchemyGoalRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyWorkoutRepository,
)
from app.infrastructure.database.repositories.conversation import (
    SqlAlchemyConversationReader,
    SqlAlchemyConversationStore,
)
from app.infrastructure.database.repositories.trace import SqlAlchemyAgentTraceRecorder
from app.infrastructure.database.session import create_engine, create_session_factory
from app.infrastructure.llm.provider import OpenAICompatibleProvider
from app.infrastructure.logging import configure_logging


@dataclass
class AppContainer:
    """进程内共享的单例对象集合，创建后挂到 FastAPI app.state 上供路由取用。"""

    settings: Settings
    clock: Clock
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    lifecycle: LifecycleDispatcher
    conversation_store: SqlAlchemyConversationStore
    conversation_reader: SqlAlchemyConversationReader
    chat_service: ChatService
    reasoner: Reasoner


def build_container(
    settings: Settings,
    *,
    reasoner: Reasoner | None = None,
    clock: Clock | None = None,
    poolclass: type[Pool] | None = None,
) -> AppContainer:
    """按依赖顺序构造所有对象。

    reasoner / clock / poolclass 允许测试替换真实 LLM、真实时钟与真实连接池。
    """
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url, poolclass=poolclass)
    sessions = create_session_factory(engine)
    lifecycle = LifecycleDispatcher()

    # 领域查询服务：Agent 能力（Capability）最终都落到这些服务上读取领域事实。
    workout_service = WorkoutQueryService(SqlAlchemyWorkoutRepository(sessions), clock)
    goal_service = GoalQueryService(SqlAlchemyGoalRepository(sessions))
    plan_service = PlanQueryService(SqlAlchemyPlanRepository(sessions))
    athlete_service = AthleteStateQueryService(SqlAlchemyAthleteStateRepository(sessions))

    # 会话写 / 读 / 执行轨迹：Conversation 生命周期与 Execution Trace 的持久化实现。
    conversation_store = SqlAlchemyConversationStore(sessions, clock)
    conversation_reader = SqlAlchemyConversationReader(sessions)
    trace_recorder = SqlAlchemyAgentTraceRecorder(sessions, clock)

    # 上下文装配器：决定每次推理前给模型哪些信息（热上下文 + 历史对话 + 记忆 + 能力清单）。
    assembler = ContextAssembler(
        working_context_provider=DomainWorkingContextProvider(
            goal_service, plan_service, athlete_service
        ),
        conversation_context_provider=SqlConversationContextProvider(conversation_reader),
        memory_context_provider=NullMemoryContextProvider(),
        capability_context_provider=StaticCapabilityContextProvider(),
        history_limit=settings.conversation_history_limit,
    )
    # Reasoner：未配置 LLM_API_KEY 时注入一个必然失败的占位实现，让错误尽早暴露而不是静默降级。
    if reasoner is None:
        if not settings.llm_api_key:
            reasoner = _MissingLLMReasoner()
        else:
            if not settings.llm_base_url or not settings.llm_model:
                raise ReasonerError("启用 LLMReasoner 时必须同时配置 LLM_BASE_URL 与 LLM_MODEL")
            reasoner = LLMReasoner(
                OpenAICompatibleProvider(
                    api_key=settings.llm_api_key,
                    base_url=settings.llm_base_url,
                    model=settings.llm_model,
                ),
                PromptRenderer(),
            )

    # AgentRuntime 只负责推理循环；ChatService 负责对话事务边界，二者职责严格分离。
    runtime = AgentRuntime(
        reasoner=reasoner,
        context_assembler=assembler,
        capability_executor=SimpleCapabilityExecutor(
            workout_service, goal_service, plan_service, athlete_service
        ),
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
    )


class _MissingLLMReasoner:
    """未配置 LLM_API_KEY 时的占位 Reasoner：任何调用都直接报错，避免静默降级。"""

    async def reason(self, context: object) -> object:
        raise ReasonerError("未配置 LLM_API_KEY，无法使用 LLMReasoner")


def create_app(
    settings: Settings | None = None,
    *,
    reasoner: Reasoner | None = None,
    clock: Clock | None = None,
    poolclass: type[Pool] | None = None,
) -> FastAPI:
    """FastAPI 应用工厂。lifespan 在进程退出时释放数据库连接池。"""
    configure_logging()
    settings = settings or Settings()
    container = build_container(settings, reasoner=reasoner, clock=clock, poolclass=poolclass)

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
    app.include_router(health_router)
    app.include_router(chat_router)
    return app
