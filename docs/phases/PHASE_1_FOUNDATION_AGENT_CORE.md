````md
# Phase 1 — Foundation & Agent Core

> Status: Active
> Depends on: `docs/ARCHITECTURE.md`
> Scope: Foundation + Coaching Domain Foundation + Agent Runtime + Lifecycle + Context
> Out of Scope: 完整 Tool Runtime、长期 Memory、Athlete State 算法、Plan Adaptation、Eval Runner

---

# 1. Phase Goal

Phase 1 的目标不是快速做出一个聊天 Demo，而是建立 Run Coach V2 后续所有模块依赖的稳定运行骨架。

完成后，系统应具备：

```text
HTTP Request
    ↓
Authentication / Request Context
    ↓
Thread / Turn / AgentRun
    ↓
Context Assembly
    ↓
Reasoner
    ↓
Action
    ↓
Capability Execution
    ↓
Observation
    ↓
Reasoner
    ↓
Final Response
    ↓
Persist Turn
    ↓
TurnCommitted
````

并确保未来可以在不修改 Agent Core 主流程的情况下接入：

```text
Tool Runtime
Memory Retrieval
Memory Projection
Athlete State
Eval Trace
Async Projector
```

Phase 1 建立的是最终架构的地基，而不是后续需要推倒的临时代码。

---

# 2. Phase 1 Deliverables

本阶段最终需要完成六部分能力：

```text
1. Project Foundation
2. Identity / Request Context
3. Coaching Domain Foundation
4. Conversation / Agent Run Model
5. Agent Runtime + Lifecycle
6. Context Assembly
```

同时提供少量用于验证 Agent Loop 的临时 Capability Adapter。

这些临时 Capability 必须通过正式 Port 接入，不能直接写进 Agent Runtime。

---

# 3. Non-Goals

Phase 1 明确不实现：

```text
Tool Registry
Tool Search
Deferred Tool Loading
MCP

Semantic Memory
Episodic Memory
Embedding Retrieval
Memory Projector

完整 Athlete State 算法
自动训练计划调整

Eval Dataset
LLM Judge
完整 Eval Runner

复杂异步 Worker
```

但是上述模块所需的：

```text
Lifecycle Hook
Event
Port
Trace Boundary
```

应在 Phase 1 中预留。

---

# 4. Target Directory

Phase 1 实际创建以下目录：

```text
backend/
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── dependencies/
│   │   │   └── context.py
│   │   ├── routes/
│   │   │   ├── health.py
│   │   │   └── chat.py
│   │   └── schemas/
│   │       └── chat.py
│   │
│   ├── identity/
│   │   ├── domain/
│   │   │   └── user.py
│   │   └── application/
│   │       └── request_context.py
│   │
│   ├── coaching/
│   │   ├── domain/
│   │   │   ├── workout/
│   │   │   │   └── models.py
│   │   │   ├── goal/
│   │   │   │   └── models.py
│   │   │   ├── plan/
│   │   │   │   └── models.py
│   │   │   └── athlete/
│   │   │       └── models.py
│   │   │
│   │   ├── application/
│   │   │   ├── workout_service.py
│   │   │   ├── goal_service.py
│   │   │   └── plan_service.py
│   │   │
│   │   └── ports/
│   │       ├── workout_repository.py
│   │       ├── goal_repository.py
│   │       └── plan_repository.py
│   │
│   ├── agent/
│   │   ├── models/
│   │   │   ├── turn.py
│   │   │   ├── run.py
│   │   │   ├── action.py
│   │   │   └── observation.py
│   │   │
│   │   ├── runtime/
│   │   │   ├── agent_runtime.py
│   │   │   └── run_context.py
│   │   │
│   │   ├── reasoning/
│   │   │   ├── reasoner.py
│   │   │   ├── llm_reasoner.py
│   │   │   └── models.py
│   │   │
│   │   ├── context/
│   │   │   ├── assembler.py
│   │   │   ├── bundle.py
│   │   │   └── providers.py
│   │   │
│   │   ├── lifecycle/
│   │   │   ├── events.py
│   │   │   ├── hooks.py
│   │   │   └── dispatcher.py
│   │   │
│   │   ├── ports/
│   │   │   ├── turn_repository.py
│   │   │   ├── run_repository.py
│   │   │   ├── capability_executor.py
│   │   │   └── conversation_reader.py
│   │   │
│   │   └── application/
│   │       └── chat_service.py
│   │
│   ├── infrastructure/
│   │   ├── database/
│   │   │   ├── session.py
│   │   │   ├── models/
│   │   │   └── repositories/
│   │   ├── llm/
│   │   │   └── provider.py
│   │   └── capabilities/
│   │       └── simple_executor.py
│   │
│   └── common/
│       ├── ids.py
│       ├── clock.py
│       ├── errors.py
│       └── types.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── scenarios/
│
├── migrations/
│
├── docs/
│   ├── ARCHITECTURE.md
│   └── phases/
│       └── PHASE_1_FOUNDATION_AGENT_CORE.md
│
└── pyproject.toml
```

Phase 1 不提前创建：

```text
memory/*
tools/*
evals/*
workers/*
```

的大量空实现。

顶层架构已经定义这些模块，但在真正进入对应 Phase 时再落目录。

---

# 5. Foundation

## 5.1 Python Project

统一使用：

```text
Python 3.12+
FastAPI
Pydantic v2
SQLAlchemy 2.x
Alembic
PostgreSQL
pytest
```

LLM Provider 通过 Adapter 封装，不允许 Agent Core 直接依赖具体模型 SDK。

例如：

```python
class LLMProvider(Protocol):
    async def generate(
        self,
        request: ModelRequest,
    ) -> ModelResponse:
        ...
```

Agent Runtime 只依赖：

```text
LLMProvider
```

而不是：

```text
OpenAI Client
Anthropic Client
...
```

---

# 6. Identity & Request Context

身份从请求入口解析一次，然后沿 Runtime 传播。

核心对象：

```python
@dataclass(frozen=True)
class RequestContext:
    user_id: UUID
    request_id: UUID
    trace_id: UUID
    timestamp: datetime
```

后续可以增加：

```text
timezone
locale
client
device
```

但 Phase 1 不需要一次性全部实现。

---

## 6.1 Trusted Boundary

`user_id` 必须来自认证系统。

禁止：

```json
{
  "user_id": "..."
}
```

作为 Chat API 的普通用户参数。

Chat 请求应该类似：

```json
{
  "thread_id": "...",
  "message": "我最近训练状态怎么样？"
}
```

用户身份由：

```text
JWT
↓
Auth Dependency
↓
RequestContext
```

生成。

---

# 7. Coaching Domain Foundation

Phase 1 不实现完整训练智能，但先固定核心 Domain Object 的身份和所有权。

---

# 8. Workout

核心模型：

```python
@dataclass
class Workout:
    id: UUID
    user_id: UUID

    started_at: datetime

    distance_m: float | None
    duration_s: int | None

    avg_heart_rate: int | None
    max_heart_rate: int | None

    workout_type: WorkoutType

    source: WorkoutSource

    created_at: datetime
```

Phase 1 只保存基础训练事实。

暂时不把：

```text
training_load
fatigue_score
quality_score
```

直接塞进 Workout。

这些属于后续 Derived State / Analysis。

---

# 9. Workout Feedback

定义独立实体：

```python
@dataclass
class WorkoutFeedback:
    id: UUID
    user_id: UUID
    workout_id: UUID

    rpe: int | None
    fatigue: int | None
    soreness: int | None

    note: str | None

    created_at: datetime
```

主观反馈和客观 Workout 分离。

---

# 10. Training Goal

```python
@dataclass
class TrainingGoal:
    id: UUID
    user_id: UUID

    goal_type: GoalType

    race_date: date | None
    race_distance_m: int | None
    target_time_s: int | None

    status: GoalStatus

    created_at: datetime
    updated_at: datetime
```

Phase 1 只需要支持：

```text
读取当前 Active Goal
```

---

# 11. Training Plan

Phase 1 定义：

```python
@dataclass
class TrainingPlan:
    id: UUID
    user_id: UUID

    version: int

    goal_id: UUID | None

    status: PlanStatus

    starts_on: date
    ends_on: date

    created_at: datetime
```

以及：

```python
@dataclass
class PlannedSession:
    id: UUID
    plan_id: UUID

    scheduled_date: date

    session_type: SessionType
    title: str
    prescription: dict
```

Phase 1 只读，不实现自动 Plan Adaptation。

---

# 12. Athlete State

Phase 1 只定义最终对象，不实现完整 Evaluator。

```python
@dataclass
class AthleteStateSnapshot:
    id: UUID
    user_id: UUID

    version: int
    as_of: datetime

    aerobic_fitness: float | None
    endurance: float | None
    fatigue: float | None
    recent_training_load: float | None
    workout_completion: float | None

    confidence: float

    algorithm_version: str

    created_at: datetime
```

Phase 1 允许：

```text
读取 latest AthleteStateSnapshot
```

但 State 更新逻辑留到后续 Coaching Intelligence Phase。

---

# 13. Repository Ports

Domain/Application 层只认识 Repository Protocol。

例如：

```python
class WorkoutRepository(Protocol):
    async def list_recent(
        self,
        *,
        user_id: UUID,
        since: datetime,
        limit: int,
    ) -> list[Workout]:
        ...

    async def get(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> Workout | None:
        ...
```

注意所有用户数据查询必须显式受到：

```text
user_id
```

约束。

---

# 14. Application Services

Repository 之上提供 Domain-facing Service。

例如：

```python
class WorkoutQueryService:

    async def get_recent_workouts(
        self,
        *,
        user_id: UUID,
        days: int,
    ) -> list[Workout]:
        ...
```

Agent Tool 未来调用的是：

```text
WorkoutQueryService
```

而不是 Repository。

依赖方向：

```text
Agent
 ↓
Capability
 ↓
Application Service
 ↓
Repository
```

---

# 15. Conversation Model

Phase 1 必须建立正式 Conversation 数据模型。

核心对象：

```text
Thread
Turn
Message
AgentRun
```

---

# 16. Thread

```python
@dataclass
class Thread:
    id: UUID
    user_id: UUID

    created_at: datetime
    updated_at: datetime
```

Thread 代表一个长期对话线程。

它不等于 Agent Run。

---

# 17. Turn

一个 Turn 表示：

```text
User Input
+
Agent Processing
+
Assistant Output
```

核心：

```python
@dataclass
class Turn:
    id: UUID
    thread_id: UUID
    user_id: UUID

    user_message_id: UUID
    assistant_message_id: UUID | None

    status: TurnStatus

    started_at: datetime
    committed_at: datetime | None
```

状态：

```text
pending
running
committed
failed
cancelled
```

只有：

```text
committed
```

可以产生：

```text
TurnCommitted
```

事件。

---

# 18. Message

Message 单独持久化：

```python
@dataclass
class Message:
    id: UUID
    thread_id: UUID
    turn_id: UUID

    role: Literal[
        "user",
        "assistant",
        "tool"
    ]

    content: str

    created_at: datetime
```

Phase 1 可以暂时不把所有 Tool Observation 保存成用户可见 Message。

Agent Run Trace 与 Conversation Message 分开。

---

# 19. AgentRun

一个 Turn 可以对应一个 AgentRun：

```python
@dataclass
class AgentRun:
    id: UUID
    turn_id: UUID
    user_id: UUID

    status: AgentRunStatus

    started_at: datetime
    completed_at: datetime | None
```

以后如果支持：

```text
retry
resume
replay
```

也不会污染 Turn 身份。

---

# 20. Run Step

Phase 1 就建议保留 Runtime Step 抽象：

```python
@dataclass
class RunStep:
    id: UUID
    run_id: UUID

    index: int

    kind: RunStepKind

    input_data: dict | None
    output_data: dict | None

    started_at: datetime
    completed_at: datetime | None
```

Step 类型至少包括：

```text
reasoning
capability_call
observation
final
```

这不是 Eval 本身。

这是以后 Eval 所依赖的 Runtime Trace。

---

# 21. Agent Action Model

Agent Reasoner 不直接返回任意 dict。

定义统一 Action：

```python
class AgentAction(BaseModel):
    type: Literal[
        "capability_call",
        "final"
    ]
```

具体：

```python
class CapabilityCallAction(BaseModel):
    type: Literal["capability_call"]

    capability: str
    arguments: dict[str, Any]
```

以及：

```python
class FinalAction(BaseModel):
    type: Literal["final"]

    content: str
```

Phase 2 引入正式 Tool Runtime 后：

```text
capability_call
```

可以平滑升级成正式 Tool Call，而不需要重写 Reasoner 主结构。

---

# 22. Observation Model

统一：

```python
class Observation(BaseModel):
    source: str

    status: Literal[
        "success",
        "error"
    ]

    data: Any | None
    error: str | None
```

Reasoner 只消费标准 Observation。

不直接感知：

```text
SQLAlchemy Result
HTTP Response
SDK Object
```

---

# 23. Reasoner Port

Agent Runtime 不直接调用模型 SDK。

定义：

```python
class Reasoner(Protocol):

    async def reason(
        self,
        context: ReasoningContext,
    ) -> AgentAction:
        ...
```

这里：

```text
Reasoner
```

负责：

```text
根据当前上下文决定下一步 Action
```

而：

```text
AgentRuntime
```

负责：

```text
执行 Action，并把 Observation 重新送回 Reasoner
```

两者职责必须分离。

---

# 24. Reasoning Context

Reasoner 每次收到：

```python
@dataclass
class ReasoningContext:
    context_bundle: ContextBundle

    steps: tuple[RunStepView, ...]

    last_observation: Observation | None
```

不要让 Reasoner 自己访问 Repository / Memory / Tool Registry。

---

# 25. Agent Runtime

核心类：

```python
class AgentRuntime:

    def __init__(
        self,
        reasoner: Reasoner,
        context_assembler: ContextAssembler,
        capability_executor: CapabilityExecutor,
        lifecycle: LifecycleDispatcher,
        run_repository: AgentRunRepository,
    ):
        ...
```

Runtime 自己只编排。

伪代码：

```python
async def run(command: AgentTurnCommand):

    run = await create_run(...)

    await lifecycle.before_turn(...)

    context = await context_assembler.assemble(...)

    await lifecycle.context_assembled(...)

    while True:

        await lifecycle.before_reasoning(...)

        action = await reasoner.reason(...)

        await lifecycle.after_reasoning(...)

        if action.type == "final":
            return await finalize(...)

        observation = await capability_executor.execute(
            action,
            execution_context,
        )

        record_step(...)
```

注意：

> Phase 1 不在 Architecture Contract 中规定固定几轮 Reasoning 或固定几次 Capability Call。

循环终止由：

```text
Reasoner Final Action
Runtime Failure
Cancellation
System-level operational protection
```

共同决定。

具体 operational limits 属于 Runtime Policy，不属于业务设计核心。

---

# 26. CapabilityExecutor

Phase 1 暂时定义：

```python
class CapabilityExecutor(Protocol):

    async def execute(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> Observation:
        ...
```

Execution Context：

```python
@dataclass(frozen=True)
class CapabilityExecutionContext:
    user_id: UUID
    run_id: UUID
    turn_id: UUID
    request_id: UUID
    timestamp: datetime
```

Phase 2 的正式：

```text
ToolExecutor
```

将实现这一 Port。

因此 Agent Runtime 不需要发生接口变化。

---

# 27. Phase 1 Simple Capability Adapter

为了验证 Loop，Phase 1 可以实现：

```text
get_recent_workouts
get_active_goal
get_active_plan
get_latest_athlete_state
```

但它们放在：

```text
infrastructure/capabilities/simple_executor.py
```

而不是：

```text
agent/runtime
```

内部可以：

```text
name
→ Application Service
```

做简单 mapping。

例如：

```python
handlers = {
    "get_recent_workouts": workout_service.get_recent_workouts,
    "get_active_goal": goal_service.get_active_goal,
}
```

Phase 2 删除这个 Adapter，替换为正式 Tool Runtime。

Agent Core 无需变化。

---

# 28. Lifecycle

Phase 1 正式实现 Lifecycle Dispatcher。

Lifecycle 不需要一开始就做完整 Plugin Framework。

先定义稳定事件模型。

---

# 29. Lifecycle Events

建议：

```text
TurnStarted

ContextAssemblyStarted
ContextAssembled

ReasoningStarted
ReasoningCompleted

CapabilityStarted
CapabilityCompleted

TurnCommitStarted
TurnCommitted

TurnFailed
```

例如：

```python
@dataclass(frozen=True)
class TurnCommitted:
    turn_id: UUID
    thread_id: UUID
    user_id: UUID

    user_message_id: UUID
    assistant_message_id: UUID

    run_id: UUID

    committed_at: datetime
```

这个 Event 未来会成为：

```text
Memory
Eval
Projector
```

的重要输入。

---

# 30. Lifecycle Dispatcher

接口：

```python
class LifecycleDispatcher:

    async def publish(
        self,
        event: LifecycleEvent,
    ) -> None:
        ...
```

Phase 1 可以使用：

```text
in-process event dispatcher
```

暂时不引入 RabbitMQ。

但 Listener 和 Publisher 必须解耦。

---

# 31. Sync vs Async Lifecycle

Phase 1 区分：

```text
Critical Lifecycle
```

和：

```text
Post-Commit Projection
```

例如：

```text
Persist assistant response
```

失败：

```text
Turn 不能 Commit
```

但未来：

```text
Semantic Memory Projector
```

失败：

```text
不应该让已经成功的用户回复变成失败 Turn
```

因此边界：

```text
Before Commit
    =
transactional / critical


After TurnCommitted
    =
projection / eventually recoverable
```

这个语义第一版就固定。

---

# 32. Context System

Context 是 Phase 1 的重点模块之一。

正式定义：

```python
@dataclass
class ContextBundle:

    system: str

    working_context: WorkingContext

    recent_messages: list[MessageView]

    semantic_memories: list[MemoryView]

    episodic_memories: list[EpisodeView]

    capabilities: list[CapabilityDefinition]

    current_input: str
```

虽然 Phase 1 中：

```text
semantic_memories = []
episodic_memories = []
```

但 Context Contract 从第一版就完整。

Phase 4 接 Memory 时不改 Reasoner API。

---

# 33. Working Context

Phase 1 正式构造：

```python
@dataclass
class WorkingContext:
    goal: GoalView | None

    active_plan: PlanSummary | None

    latest_athlete_state: AthleteStateView | None

    critical_constraints: tuple[str, ...]
```

Phase 1：

```text
critical_constraints
```

可以为空。

未来 Memory Semantic Projection 可以向这里提供高优先级约束。

---

# 34. Context Providers

ContextAssembler 不直接依赖数据库。

采用 Provider：

```python
class WorkingContextProvider(Protocol):
    async def load(...):
        ...

class ConversationContextProvider(Protocol):
    async def load(...):
        ...

class MemoryContextProvider(Protocol):
    async def load(...):
        ...

class CapabilityContextProvider(Protocol):
    async def load(...):
        ...
```

Phase 1：

```text
MemoryContextProvider
```

使用：

```text
NullMemoryContextProvider
```

返回空结果。

Phase 4 直接替换实现。

---

# 35. ContextAssembler

```python
class ContextAssembler:

    async def assemble(
        self,
        request: ContextAssemblyRequest,
    ) -> ContextBundle:
        ...
```

负责组合：

```text
System Instructions

Working Context

Recent Conversation

Semantic Memories

Episodes

Available Capabilities

Current Input
```

但不负责：

```text
SQL
Vector Search
Domain Calculation
```

这些属于 Provider。

---

# 36. Recent Conversation

Phase 1 建议只提供有限 Recent Conversation。

原因不是把历史遗忘，而是：

```text
Long-term History
```

以后属于 Memory / Compaction 问题。

因此：

```text
ConversationContextProvider
```

负责：

```text
读取最近若干已提交 Message
```

具体 Context Budget 后续可以改，但接口保持稳定。

---

# 37. Prompt Renderer

建议 Reasoner 内部再有：

```text
ContextBundle
     ↓
PromptRenderer
     ↓
ModelRequest
```

而不是 ContextAssembler 输出大字符串。

也就是说：

```text
Context Assembly
```

负责：

> 有哪些信息。

```text
Prompt Rendering
```

负责：

> 怎么给模型表达。

两者分开。

---

# 38. Database Tables

Phase 1 只建真正需要的表。

---

## 38.1 Identity

```text
users
```

核心：

```text
id
created_at
updated_at
```

认证字段根据最终 Auth 实现决定。

---

## 38.2 Coaching

```text
workouts
workout_feedback

training_goals

training_plans
planned_sessions

athlete_state_snapshots
```

`plan_changes` 可以先建表但 Phase 1 暂不写入，也可以在 Plan Adaptation Phase 再 migration。

---

## 38.3 Agent

必须：

```text
threads
messages
turns
agent_runs
run_steps
```

---

# 39. Recommended Agent Persistence Model

关系：

```text
User
 │
 ▼
Thread
 │
 ├─────────────┐
 ▼             ▼
Turn         Turn
 │
 ├── User Message
 ├── Assistant Message
 │
 └── AgentRun
       │
       ├── Step 1
       ├── Step 2
       └── Step N
```

Conversation Facts：

```text
messages
turns
```

和 Runtime Trace：

```text
agent_runs
run_steps
```

分开。

---

# 40. Transaction Boundary

Turn Commit 建议采用数据库事务：

```text
BEGIN

persist assistant message

update turn
    status = committed
    assistant_message_id = ...
    committed_at = ...

update agent_run
    status = completed

COMMIT
```

事务成功后才发布：

```text
TurnCommitted
```

必须满足：

```text
DB Commit
    ↓
TurnCommitted
```

禁止：

```text
TurnCommitted
    ↓
DB Commit
```

否则 projector 可能读取到尚未存在的数据。

---

# 41. Failure Semantics

如果 Reasoner / Capability 执行失败：

```text
AgentRun
status = failed

Turn
status = failed
```

已经保存的：

```text
User Message
```

仍然可以保留。

但：

```text
TurnCommitted
```

不发布。

未来 Memory Projector 因此不会把失败交互当长期事实学习。

---

# 42. Cancellation

Phase 1 为 Turn 设计：

```text
cancelled
```

状态。

Runtime 应捕获：

```text
asyncio.CancelledError
```

并执行生命周期收尾。

取消的 Turn：

```text
不发布 TurnCommitted
```

未来如果产品希望中断消息也成为 Conversation Fact，可以通过单独语义设计，而不是默认等价于正常 committed Turn。

---

# 43. Chat Application Service

API 不直接操作 Agent Runtime。

入口：

```python
class ChatService:

    async def send_message(
        self,
        *,
        request_context: RequestContext,
        thread_id: UUID | None,
        content: str,
    ) -> ChatResult:
        ...
```

内部：

```text
Resolve/Create Thread
       ↓
Persist User Message
       ↓
Create Turn
       ↓
AgentRuntime.run
       ↓
Persist Assistant
       ↓
Commit Turn
```

---

# 44. API

Phase 1 需要：

```text
POST /api/v1/chat
GET  /api/v1/threads/{thread_id}/messages
GET  /health
```

Chat：

```json
{
  "thread_id": "optional",
  "message": "我最近训练状态怎么样？"
}
```

响应：

```json
{
  "thread_id": "...",
  "turn_id": "...",
  "message_id": "...",
  "content": "..."
}
```

---

# 45. SSE

Phase 1 可以支持基础 SSE，但不要让 SSE 侵入 Agent Runtime。

Runtime 发布：

```text
Lifecycle Event
```

SSE Adapter 把部分事件映射为：

```text
run.started
reasoning.started
capability.started
capability.completed
response.delta
run.completed
```

也就是说：

```text
Agent Runtime
      ↓
Event
      ↓
SSE Adapter
      ↓
Frontend
```

而不是：

```python
agent_runtime.send_sse(...)
```

---

# 46. Initial System Prompt

Phase 1 Prompt 不应承担业务数据库职责。

System Prompt 主要定义：

```text
你是长期跑步训练教练 Agent。

需要根据已提供的跑者状态和工具能力完成当前任务。

当已有信息不足时，可以主动使用可用能力获取证据。

不要声称获取了上下文中不存在的数据。

训练建议应说明主要判断依据。
```

不要在 Prompt 里硬编码：

```text
固定 Workflow
固定工具顺序
固定 Intent Routing
```

这些会削弱 Agent Runtime 的自主推理设计。

---

# 47. Phase 1 Vertical Slice

Phase 1 的核心验收场景：

数据库预置：

```text
Goal:
半马 1:50

Recent Workouts:
8/20 easy 8km
8/22 tempo 10km
8/24 long run 18km
8/27 interval 8km

Latest Athlete State:
fatigue = moderate
recent_training_load = rising

Plan:
当前第 6 周
```

用户：

```text
“我最近训练状态怎么样？”
```

期望运行：

```text
User Input
    ↓
Context Assembly
    │
    ├── Current Goal
    ├── Active Plan
    └── Latest Athlete State
    ↓
Reasoner
    ↓
get_recent_workouts
    ↓
Observation
    ↓
Reasoner
    ↓
Final Answer
```

重点不是回答文案有多漂亮。

重点检查：

```text
是否正确构建 Turn
是否正确生成 AgentRun
是否经过 ContextAssembler
是否通过 CapabilityExecutor 获取数据
是否产生 Observation
是否正确持久化 Step
是否正确 Commit
是否发布 TurnCommitted
```

---

# 48. Second Scenario

用户：

```text
“下周我要比赛，现在计划是什么？”
```

Reasoner 可以：

```text
直接利用 Working Context
```

或者：

```text
get_active_plan
```

取决于当前 Context 是否已经充分。

系统不能硬编码：

```text
if message contains "计划":
    get_active_plan()
```

这是 Reasoner 的判断。

---

# 49. Unit Tests

Phase 1 至少覆盖：

```text
Domain model invariants

Repository user isolation

Context assembly

Reasoner action parsing

Capability execution context

Agent runtime:
    action → observation → reason

Turn commit

Turn failure

Lifecycle event ordering
```

---

# 50. Integration Tests

至少验证：

```text
PostgreSQL Repository

Chat API

完整 Agent Turn

TurnCommitted after DB commit

Failed Turn does not publish TurnCommitted
```

---

# 51. Scenario Tests

不要只写单元测试。

增加：

```text
tests/scenarios/
```

例如：

```text
test_recent_training_analysis.py
test_current_plan_question.py
test_goal_context.py
```

暂时使用 Fake LLM Reasoner 或 deterministic scripted reasoner。

这样可以稳定验证 Agent Runtime，而不是每次测试都花真实模型费用。

---

# 52. Observability

Phase 1 所有运行至少具有：

```text
request_id
trace_id
user_id
thread_id
turn_id
run_id
```

日志中所有 Agent 执行都应能够通过：

```text
run_id
```

串联。

---

# 53. Logging

建议结构化日志：

```json
{
  "event": "agent.capability.completed",
  "request_id": "...",
  "turn_id": "...",
  "run_id": "...",
  "capability": "get_recent_workouts",
  "duration_ms": 42,
  "status": "success"
}
```

不要依赖大量：

```python
logger.info("进来了")
```

式调试日志。

---

# 54. Error Model

统一定义应用异常层次：

```text
RunCoachError

DomainError

ApplicationError

AgentRuntimeError

ReasonerError

CapabilityError

InfrastructureError
```

Infrastructure Exception 不直接暴露给 LLM 或客户端。

例如：

```text
asyncpg.exceptions.ConnectionError
```

不能直接成为 Observation：

```text
数据库连接 xxx.xxx.xxx 失败
```

应归一化。

---

# 55. Phase 1 Architectural Invariants

完成 Phase 1 后必须满足：

```text
Agent Runtime 不 import SQLAlchemy ORM。

Reasoner 不 import Repository。

ContextAssembler 不执行 SQL。

LLM 不决定 user_id。

Capability 不直接读取 HTTP Request。

TurnCommitted 只在 DB Commit 后产生。

失败 Turn 不触发长期 Projection 事件。

Athlete State 和 Workout 不混表。

Conversation Message 和 Agent Trace 分开。

Memory 暂时为空，但已经存在正式接入位置。

Tool Runtime 暂时未实现，但 Agent Runtime 已通过 Port 与其解耦。
```

任何实现如果违反上述规则，即使功能能够运行，也视为 Phase 1 未完成。

---

# 56. Phase 1 Implementation Order

建议按以下顺序落地：

```text
Step 1
Project Foundation
FastAPI / SQLAlchemy / Alembic / Config

        ↓

Step 2
Identity
RequestContext
User Isolation

        ↓

Step 3
Coaching Domain
Workout / Goal / Plan / AthleteState
Repository Ports

        ↓

Step 4
Conversation Persistence
Thread / Message / Turn / AgentRun / RunStep

        ↓

Step 5
Lifecycle
Events / Dispatcher / TurnCommitted

        ↓

Step 6
Context System
Providers / WorkingContext / ContextBundle

        ↓

Step 7
Reasoner
Reasoner Port / LLM Adapter / Action Model

        ↓

Step 8
Capability Port
Simple Capability Adapter

        ↓

Step 9
Agent Runtime
Reason → Action → Observation → Reason

        ↓

Step 10
Chat Application
FastAPI Endpoint

        ↓

Step 11
Trace / Structured Logging / SSE

        ↓

Step 12
Scenario Tests
```

不要先写 Agent Loop，然后回头补数据模型。

先把状态和生命周期边界建好。

---

# 57. Phase 1 Definition of Done

Phase 1 完成需要同时满足：

### Architecture

```text
模块依赖符合 ARCHITECTURE.md
无跨层 ORM 调用
Runtime / Domain / Infrastructure 边界清晰
```

### Domain

```text
Workout
Goal
Plan
AthleteStateSnapshot

模型与 Repository Port 可正常工作
```

### Agent

```text
Thread
Turn
AgentRun
RunStep

完整生命周期可运行
```

### Context

```text
Working Context
Recent Conversation
Capability Context

统一通过 ContextAssembler 进入 Reasoner
```

### Runtime

```text
Reason
→ Capability Call
→ Observation
→ Reason
→ Final
```

完整执行成功。

### Persistence

```text
User Message
Assistant Message
Turn
AgentRun
RunStep
```

均能够正常持久化。

### Lifecycle

正常执行：

```text
TurnStarted
...
TurnCommitted
```

失败执行：

```text
TurnStarted
...
TurnFailed
```

且不会错误发送 `TurnCommitted`。

### Tests

Unit、Integration、Scenario 三层测试通过。

---

# 58. What Phase 1 Must Leave for Phase 2

Phase 1 最终应该留下一个非常清晰的接口：

```text
AgentRuntime
        │
        ▼
CapabilityExecutor
```

Phase 1：

```text
CapabilityExecutor
        ↓
SimpleCapabilityExecutor
```

Phase 2：

```text
CapabilityExecutor
        ↓
ToolRuntime
        │
        ├── Tool Registry
        ├── Tool Catalog
        ├── Tool Search
        ├── Tool Resolver
        └── Tool Executor
```

替换之后：

```text
Agent Runtime
Reasoner
Context
Lifecycle
```

全部不需要推倒重写。

这就是 Phase 1 是否设计成功的一个重要判断标准。

---

# 59. What Phase 1 Must Leave for Memory

同样：

```text
ContextAssembler
      ↓
MemoryContextProvider
```

Phase 1：

```text
NullMemoryContextProvider
```

Phase 4：

```text
MemoryContextProvider
        │
        ├── SemanticMemoryRetriever
        └── EpisodicMemoryRetriever
```

以及：

```text
TurnCommitted
       ↓
PostCommit Listener
```

未来：

```text
SemanticMemoryProjector
EpisodeProjector
```

直接订阅。

Agent Core 无需出现：

```python
if memory_enabled:
```

这也是 Phase 1 的核心成功标准。

---

# 60. Phase 1 Summary

Phase 1 最终建立：

```text
                    HTTP
                     │
                     ▼
               RequestContext
                     │
                     ▼
                ChatService
                     │
                     ▼
                 AgentRun
                     │
                     ▼
             ContextAssembler
               /     |      \
              /      |       \
       Working    Recent     Memory Port
       Context  Conversation    (Null)
              \      |       /
               \     |      /
                Reasoner
                    │
              Agent Action
                    │
          CapabilityExecutor
                    │
             Domain Service
                    │
               PostgreSQL
                    │
              Observation
                    │
                Reasoner
                    │
               Final Output
                    │
                 Commit
                    │
             TurnCommitted
                    │
          Future Projectors
```

Phase 1 解决的不是：

> “Run Coach 已经有多少功能？”

而是：

> **从今天开始，任何新能力应该放在哪里、由谁拥有、通过什么接口进入 Agent、在什么生命周期修改状态。**

这个问题一旦解决，Phase 2 的 Tool Runtime、Phase 3 的 Coaching Intelligence、Phase 4 的 Memory 和 Phase 5 的 Eval 都可以作为独立模块逐步长出来，而不再改变 Agent Core 的基本形态。

```

这版 Phase 1 里有一个我刻意做的调整：**没有先做“弱化版 ToolRegistry”**，而是只定义 `CapabilityExecutor` Port。因为我们已经决定 Phase 2 要把 Tool System 一次做到正式架构，那么 Phase 1 再做一个半成品 Registry 反而是重复劳动。

同理，Memory 这里直接预留 `MemoryContextProvider + TurnCommitted` 两个接缝，但不先造一个“简单 pgvector Memory”。这样 Phase 1 写完之后，Phase 2/4 都是在往插槽里装正式实现，而不是拆旧实现。
```
