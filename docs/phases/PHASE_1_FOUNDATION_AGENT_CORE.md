# Phase 1 — Foundation & Agent Core

> Status: Completed
> Depends on: `docs/ARCHITECTURE.md`
> Next: `docs/phases/PHASE_2_DYNAMIC_TOOL_RUNTIME.md`
> Scope: Foundation + Coaching Domain Foundation + Agent Runtime + Lifecycle + Context
> Out of Scope: 完整 Tool Runtime、长期 Memory、Athlete State 算法、Plan Adaptation、Eval Runner

---

# 1. Phase Goal

Phase 1 的目标不是快速做出聊天 Demo，而是建立 Run Coach V2 后续所有模块依赖的稳定运行骨架。

完成后，系统应具备：

```text
HTTP Request
    ↓
Authentication / RequestContext
    ↓
ChatService
    ↓
Transaction A:
Thread / User Message / Turn / AgentRun
    ↓
AgentRuntime
    ↓
ContextBundle + ReasoningState
    ↓
Reason → Action → Capability → Observation → Reason
    ↓
FinalAction
    ↓
Transaction B:
Assistant Message / Turn Commit / AgentRun Complete
    ↓
TurnCommitted
```

并确保未来可以在不修改 Agent Core 主流程的情况下接入：

```text
Tool Runtime
Memory Retrieval
Memory Projection
Athlete State Evaluator
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
│   │   │   ├── workout/models.py
│   │   │   ├── goal/models.py
│   │   │   ├── plan/models.py
│   │   │   └── athlete/models.py
│   │   ├── application/
│   │   │   ├── workout_service.py
│   │   │   ├── goal_service.py
│   │   │   └── plan_service.py
│   │   └── ports/
│   │       ├── workout_repository.py
│   │       ├── goal_repository.py
│   │       └── plan_repository.py
│   │
│   ├── agent/
│   │   ├── models/
│   │   │   ├── thread.py
│   │   │   ├── message.py
│   │   │   ├── turn.py
│   │   │   ├── run.py
│   │   │   ├── action.py
│   │   │   └── observation.py
│   │   ├── runtime/
│   │   │   ├── agent_runtime.py
│   │   │   └── run_context.py
│   │   ├── reasoning/
│   │   │   ├── reasoner.py
│   │   │   ├── state.py
│   │   │   ├── llm_reasoner.py
│   │   │   └── models.py
│   │   ├── context/
│   │   │   ├── assembler.py
│   │   │   ├── bundle.py
│   │   │   └── providers.py
│   │   ├── lifecycle/
│   │   │   ├── events.py
│   │   │   └── dispatcher.py
│   │   ├── ports/
│   │   │   ├── conversation_store.py
│   │   │   ├── conversation_reader.py
│   │   │   ├── trace_recorder.py
│   │   │   └── capability_executor.py
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
├── migrations/
└── pyproject.toml
```

Phase 1 不提前创建 `memory/*`、`tools/*`、`evals/*`、`workers/*` 的空实现。顶层架构已经定义这些模块，在进入对应 Phase 时再落目录。

---

# 5. Foundation

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

具体模型 SDK 必须封装在 LLM Provider Adapter 后：

```python
class LLMProvider(Protocol):
    async def generate(
        self,
        request: ModelRequest,
    ) -> ModelResponse:
        ...
```

依赖方向必须固定为：

```text
AgentRuntime
    ↓
Reasoner

LLMReasoner
    ↓
LLMProvider
```

AgentRuntime 只依赖 `Reasoner`，不依赖也不感知 `LLMProvider`，更不需要知道底层是否使用 LLM。

Scenario Test 可以直接以 `ScriptedReasoner` 或 `FakeReasoner` 替换 `LLMReasoner`。

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

`WorkoutFeedback` 保存用户报告的原始主观事实：

```python
@dataclass
class WorkoutFeedback:
    id: UUID
    user_id: UUID
    workout_id: UUID

    # 本次训练的主观用力程度，采用 1~10 量表。
    perceived_exertion: int | None

    # 用户自己报告的整体疲劳程度。
    # 这是主观事实，不等同于 AthleteState 中系统推导的疲劳状态。
    subjective_fatigue: int | None

    # 用户自己报告的训练后肌肉酸痛程度。
    soreness: int | None

    # 用户对训练感受、身体状态等情况的自然语言补充。
    note: str | None

    created_at: datetime
```

必须明确区分：

```text
WorkoutFeedback
=
用户报告的原始主观事实

AthleteStateSnapshot
=
系统结合多种证据后的推导状态
```

Phase 1 固定主观量表的字段语义并校验 `perceived_exertion` 为 1～10；其他量表的范围应在实现前明确。反馈如何进入状态算法属于 Phase 3。

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

Phase 1 只定义快照的版本化、时间边界和基础状态语义，不实现完整 Evaluator：

```python
@dataclass
class AthleteStateSnapshot:
    id: UUID
    user_id: UUID

    # 用户维度下单调递增的状态版本。
    version: int

    # 这份状态使用的事实数据截止到什么时间。
    as_of: datetime

    # 系统推导的当前疲劳等级。
    fatigue_level: FatigueLevel | None

    # 系统推导的当前恢复状态。
    recovery_level: RecoveryLevel | None

    # 近期训练负荷指标。
    # 具体定义和计算方式属于 Phase 3。
    recent_training_load: float | None

    # 当前统计窗口内计划训练的完成比例。
    # 统计窗口和具体计算方式属于 Phase 3。
    workout_completion_rate: float | None

    # 系统对当前状态判断的整体可信程度。
    confidence: float | None

    # 生成该状态快照的算法版本。
    algorithm_version: str

    created_at: datetime
```

Phase 1 允许读取 latest `AthleteStateSnapshot`，但不定义或虚构 `aerobic_fitness`、`endurance`、`threshold_fitness`、`pace_hr_trend` 等未经研究的指标。

具体指标定义、数值范围、计算窗口和算法属于 Phase 3 Coaching Intelligence。

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

Phase 1 必须建立三套职责不同的状态模型：

```text
Conversation State
├── Thread
├── Message
└── Turn

Runtime Working State
└── ReasoningState

Execution Trace
├── AgentRun
└── RunStep
```

分别回答：

```text
Conversation State
→ 用户真正经历了什么？

ReasoningState
→ 当前 Run 内 Agent 已经知道和做过什么？

Execution Trace
→ Agent 当时实际上怎么完成任务？
```

三套状态必须分离。`RunStep` 是持久化审计记录，不能被当作 AgentRuntime 的工作状态。

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

Message 只保存用户与助手实际形成的 Canonical Conversation：

```python
class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    id: UUID
    thread_id: UUID
    turn_id: UUID

    role: MessageRole
    content: str

    created_at: datetime
```

Capability Call、Observation、Reasoning、内部模型调用等执行信息不得写入 `messages`，统一由 `AgentRun / RunStep` 记录。

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

`RunStep` 是持久化 Execution Trace，不是 Runtime Working State：

```python
@dataclass
class RunStep:
    id: UUID
    run_id: UUID

    index: int
    kind: RunStepKind

    # 仅 capability_call / observation 使用，
    # 用于把一次能力调用与其结果关联。
    call_id: UUID | None

    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None

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

同一次 Capability Call 与对应 Observation 使用相同 `call_id`。

`reasoning` Step 只能保存模型调用元数据和最终 Action，不保存隐藏 Chain of Thought。

## 20.1 ReasoningState

`ReasoningState` 是当前 AgentRun 内存中的工作状态：

```python
ReasoningInteraction = CapabilityCallAction | Observation


@dataclass
class ReasoningState:
    interactions: list[ReasoningInteraction]
```

典型状态：

```text
Action
get_recent_workouts(days=14)

Observation
返回最近 4 次训练

Action
get_active_plan()

Observation
返回当前计划
```

它不保存隐藏 Chain of Thought，不属于数据库 Canonical State，也不通过查询 `run_steps` 恢复并驱动正常 Agent 执行。

`FinalAction` 不追加进 `ReasoningState`，因为 Final 产生后 Runtime 已结束。

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
    state: ReasoningState
```

第一次 Reasoning 使用：

```text
ContextBundle
+
empty ReasoningState
```

后续 Reasoning 使用同一 `ContextBundle`，并由 `ReasoningState.interactions` 提供已发生的 Capability Call 与 Observation。

Reasoner 不访问 Repository、Memory、Tool Registry 或 `RunStep`，也不再单独接收 `last_observation`。

---

# 25. Agent Runtime

AgentRuntime 只拥有 Reason–Act–Observe 执行，不拥有 Conversation 生命周期：

```python
class AgentRuntime:
    def __init__(
        self,
        reasoner: Reasoner,
        context_assembler: ContextAssembler,
        capability_executor: CapabilityExecutor,
        lifecycle: LifecycleDispatcher,
        trace_recorder: AgentTraceRecorder,
    ):
        ...
```

ChatService 在调用 Runtime 前已经创建 `Turn` 与 `AgentRun`。Runtime 接收可信 ID 和当前输入，最终只返回 `FinalAction`：

```python
async def run(command: AgentTurnCommand) -> FinalAction:
    context_bundle = await context_assembler.assemble(...)
    state = ReasoningState(interactions=[])

    while True:
        action = await reasoner.reason(
            ReasoningContext(
                context_bundle=context_bundle,
                state=state,
            )
        )

        if isinstance(action, FinalAction):
            await trace_recorder.record_final(action=action)
            return action

        call_id = uuid4()
        await trace_recorder.record_action(
            call_id=call_id,
            action=action,
        )
        state.interactions.append(action)

        observation = await capability_executor.execute(
            name=action.capability,
            arguments=action.arguments,
            context=execution_context,
        )

        state.interactions.append(observation)
        await trace_recorder.record_observation(
            call_id=call_id,
            observation=observation,
        )
```

AgentRuntime 不执行：

```text
create Thread
create Turn
create AgentRun
persist Assistant Message
commit / fail / cancel Turn
```

Runtime 不通过读取 `RunStep` 驱动 Reasoning。`RunStep` 仅由 `AgentTraceRecorder` 持久化为审计与 Eval 依据。

循环终止由 Reasoner Final Action、typed failure、cancellation 与系统级运行保护共同决定；Phase 1 不把固定 Reasoning 次数或 Capability Call 次数写成业务契约。

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

Phase 1 正式实现稳定的 Lifecycle Event 与 Dispatcher，但不构建完整 Plugin Framework。

Lifecycle Event 分为：

```text
Conversation Lifecycle
→ 由 ChatService 发布

Agent Execution Lifecycle
→ 由 AgentRuntime 发布
```

同一事件只能有一个 Owner，禁止 ChatService 与 AgentRuntime 重复发布。

---

# 29. Lifecycle Events

| Event | Owner |
|---|---|
| `TurnStarted` | ChatService |
| `ContextAssemblyStarted` | AgentRuntime |
| `ContextAssembled` | AgentRuntime |
| `ReasoningStarted` | AgentRuntime |
| `ReasoningCompleted` | AgentRuntime |
| `CapabilityStarted` | AgentRuntime |
| `CapabilityCompleted` | AgentRuntime |
| `TurnCommitStarted` | ChatService |
| `TurnCommitted` | ChatService |
| `TurnFailed` | ChatService |
| `TurnCancelled` | ChatService |

`TurnCommitted` 至少包含：

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

它是未来 Memory、Eval 与异步 Projector 的重要输入。

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

Phase 1 使用 in-process Dispatcher，Listener 与 Publisher 保持解耦，不引入 RabbitMQ 或 Transactional Outbox。

已知可靠性边界：

```text
DB COMMIT
    ↓
process crash
    ↓
TurnCommitted 尚未 publish
```

Phase 1 明确接受这个 crash window。后续只有在 Memory Projection 等能力提出更高可靠性要求时，才设计 Transactional Outbox。

---

# 31. Sync vs Async Lifecycle

必须区分：

```text
Before final DB Commit
=
transactional / critical

After TurnCommitted
=
projection / eventually recoverable
```

持久化 Assistant Message、将 Turn 置为 committed、将 AgentRun 置为 completed 中任何一步失败，都不能发布 `TurnCommitted`。

未来 Semantic Memory Projector 等后提交监听器失败，不应把已经成功提交的用户回复改成失败 Turn；其重试和可靠投递机制在对应 Phase 设计。

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

ContextAssembler 不直接依赖数据库，统一通过 Provider：

```python
class WorkingContextProvider(Protocol):
    async def load(...):
        ...

class ConversationContextProvider(Protocol):
    async def load(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_turn_id: UUID,
    ) -> list[MessageView]:
        ...

class MemoryContextProvider(Protocol):
    async def load(...):
        ...

class CapabilityContextProvider(Protocol):
    async def load(...):
        ...
```

Phase 1 的 `MemoryContextProvider` 使用 `NullMemoryContextProvider` 返回空结果，Phase 4 直接替换实现。

`ConversationContextProvider` 必须显式接收 `exclude_turn_id`，保证当前 Turn 的 User Message 不会同时进入 `recent_messages` 与 `current_input`。

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

`ConversationContextProvider` 只读取有限数量、属于历史 committed Turn 的 user / assistant Message。

硬规则：

```text
recent_messages
=
历史 committed Turn 的 Canonical Conversation
-
当前 Turn

current_input
=
当前用户输入，且只出现一次
```

Transaction A 已经持久化的当前 User Message 必须通过 `exclude_turn_id` 排除。Failed / Cancelled Turn 中保留的 User Message 也不能污染后续正常 Conversation Context。

长期历史的压缩与检索属于后续 Memory / Compaction 问题；Context Budget 可以演进，但上述去重和 committed-only 语义不能改变。

---

# 37. Prompt Renderer

Prompt Renderer 的输入是：

```text
ContextBundle
      +
ReasoningState
      ↓
PromptRenderer
      ↓
ModelRequest
```

第一次 Reasoning 渲染 `ContextBundle + empty ReasoningState`；后续轮次将 Capability Call 与 Observation 从 `ReasoningState.interactions` 一并表达给模型。

Context Assembly 负责“有哪些信息”，Prompt Rendering 负责“如何给模型表达”。PromptRenderer 不读取 `RunStep`，也不渲染隐藏 Chain of Thought。

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

持久化关系：

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
 ├── Assistant Message（仅 committed Turn）
 │
 └── AgentRun
       │
       ├── RunStep 1
       ├── RunStep 2
       └── RunStep N
```

三类状态的持久化语义：

```text
Conversation Facts
=
threads / messages / turns

Runtime Working State
=
ReasoningState，仅存在于当前 AgentRun 内存

Execution Trace
=
agent_runs / run_steps
```

`messages` 只包含 user / assistant Canonical Conversation；Capability Call 与 Observation 通过带相同 `call_id` 的 `run_steps` 关联。

---

# 40. Transaction Boundary

ChatService 使用两个短事务管理一次用户交互。禁止数据库事务跨越 LLM 或 Capability 执行过程。

## Transaction A：Start Turn

```text
BEGIN

Validate / Create Thread

Create Turn
    status = pending

Insert User Message

Turn.user_message_id = message.id

Create AgentRun
    status = running

Turn.status = running

COMMIT
```

提交成功后由 ChatService 发布 `TurnStarted`，然后 AgentRuntime 才开始执行。

## Agent Runtime：事务外执行

```text
Context Assemble
Reason
Act
Observe
Reason
...
FinalAction
```

## Transaction B：Commit Turn

```text
BEGIN

Insert Assistant Message

Update Turn
    assistant_message_id = ...
    status = committed
    committed_at = ...

Update AgentRun
    status = completed
    completed_at = ...

Optional:
Update Thread.updated_at

COMMIT
```

只有 Transaction B 成功后，ChatService 才发布：

```text
DB COMMIT
    ↓
TurnCommitted
```

禁止在 Commit 前发布事件，否则 Projector 可能读取到尚未存在的数据。

---

# 41. Failure Semantics

AgentRuntime 负责停止内部 Reason / Capability 执行、释放 Runtime 资源，并向 ChatService 传播 typed failure。

最终持久化状态由 ChatService 负责：

```text
BEGIN

Turn.status = failed
AgentRun.status = failed

COMMIT
```

已保存的 User Message 可以保留，但不得创建 committed Assistant Message。事务成功后 ChatService 发布 `TurnFailed`，绝不发布 `TurnCommitted`，因此失败交互不会触发长期 Memory Projection。

---

# 42. Cancellation

AgentRuntime 捕获取消信号时，只负责停止内部执行、释放资源并传播 cancellation，不直接修改 Turn 或 AgentRun。

ChatService 负责持久化：

```text
BEGIN

Turn.status = cancelled
AgentRun.status = cancelled

COMMIT
```

随后发布 `TurnCancelled`，不发布 `TurnCommitted`。

取消 Turn 中已经保存的 User Message 可以保留，但不等价于正常 Canonical Conversation History；如果未来产品需要展示或恢复中断交互，应单独设计语义。

---

# 43. Chat Application Service

ChatService 是一次用户交互的 Application Orchestrator，拥有 Thread、Message、Turn、AgentRun 的 Conversation 生命周期与事务边界；AgentRuntime 只负责执行 Agent reasoning loop。

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

完整流程：

```text
Resolve / Create Thread
        ↓
ConversationStore.start_turn()
        ↓
Transaction A COMMIT
        ↓
TurnStarted
        ↓
AgentRuntime.run(turn_id, run_id, ...)
        ↓
FinalAction
        ↓
TurnCommitStarted
        ↓
ConversationStore.commit_turn()
        ↓
Transaction B COMMIT
        ↓
TurnCommitted
```

为避免 ChatService 依赖多个细碎 Repository 与 SQLAlchemy Session，定义应用级 Port：

```python
class ConversationStore(Protocol):
    async def start_turn(...) -> StartedTurn:
        ...

    async def commit_turn(...) -> CommittedTurn:
        ...

    async def fail_turn(...) -> None:
        ...

    async def cancel_turn(...) -> None:
        ...
```

Infrastructure 实现负责真实 SQLAlchemy Transaction。ChatService 拥有事务语义，但不直接操作 ORM 或 Session。

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

`response.delta` 是流式正文增量：由 `ResponseDelta` 生命周期事件承载，
随模型生成逐片段推送（载荷含 `step_index`），不是 Turn 提交后一次性发出
的完整正文。它不是 canonical 内容，增量聚合结果必须与 commit_turn 落库的
助手正文一致（集成测试守卫此契约）。

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
fatigue_level = moderate
recent_training_load = fixture value

Plan:
当前第 6 周
```

这里的 `AthleteStateSnapshot` 是测试 Fixture / Seed Data，仅用于验证 ContextAssembler 与 AgentRuntime 能读取状态，不代表 Phase 1 已实现状态计算算法。

用户：

```text
“我最近训练状态怎么样？”
```

期望运行：

```text
ChatService
    ↓
Transaction A Commit
    ↓
AgentRuntime
    ↓
Context Assembly
    │
    ├── Current Goal
    ├── Active Plan
    └── Seed AthleteStateSnapshot
    ↓
Reasoner
    ↓
get_recent_workouts
    ↓
Observation
    ↓
Reasoner
    ↓
FinalAction
    ↓
Transaction B Commit
    ↓
TurnCommitted
```

重点检查：

```text
ConversationStore 是否正确建立 Turn / User Message / AgentRun
ContextAssembler 是否排除当前 Turn 并避免 current_input 重复
CapabilityExecutor 是否获得可信 ExecutionContext
ReasoningState 是否按 Action / Observation 演进
RunStep 是否使用 call_id 关联调用与结果
FinalAction 是否由 ChatService 正确 Commit
TurnCommitted 是否只在 Transaction B 成功后发布
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

Phase 1 不要求为了“Unit 层存在”机械补测试。

仅对复杂纯逻辑、关键状态转换，以及无需外部依赖即可验证的高风险逻辑编写必要 Unit Test，例如：

```text
Reasoner Action parsing
ReasoningState interaction ordering
Domain invariants with non-trivial boundaries
Lifecycle event value semantics
```

简单数据模型、薄封装、CRUD 与显而易见的映射不单独补低价值 Unit Test。

---

# 50. Integration Tests

Phase 1 以 Integration Test 为主要验收手段，重点验证：

```text
ConversationStore start / commit transaction
ConversationStore fail / cancel transaction
Repository user isolation
ChatService complete turn
TurnCommitted after Transaction B commit
Failed / Cancelled Turn never publishes TurnCommitted
ConversationContextProvider committed-only and current-turn exclusion
Capability execution with trusted context
PostgreSQL repositories and Chat API
```

---

# 51. Scenario Tests

Scenario Test 验证完整 Agent 行为链：

```text
Context
→ Reason
→ Capability
→ Observation
→ Reason
→ Final
→ Commit
```

至少包含：

```text
test_recent_training_analysis.py
test_current_plan_question.py
test_goal_context.py
test_failed_turn.py
test_cancelled_turn.py
```

使用 `ScriptedReasoner` 或 `FakeReasoner` 稳定验证 Runtime，不依赖真实模型费用或非确定输出。

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

1. Conversation State、Runtime Working State 与 Execution Trace 必须分离。
2. Message 只保存 user / assistant Canonical Conversation。
3. AgentRuntime 不通过读取 RunStep 驱动正常 Reasoning。
4. ReasoningState 只存在于当前 AgentRun 生命周期，用于维护 Action / Observation 工作状态。
5. ChatService 拥有 Conversation 生命周期与事务边界；AgentRuntime 不创建 AgentRun，也不提交 Turn。
6. AgentRuntime 只负责 Context → Reason → Action → Observation → Reason → Final。
7. 当前 User Message 只通过 `ContextBundle.current_input` 提供；`recent_messages` 只包含历史 committed Turn，且排除当前 Turn。
8. `TurnCommitted` 必须在最终数据库事务成功之后发布。
9. 失败或取消 Turn 可以保留 User Message，但不能形成 committed Assistant Message，也不能触发长期 Memory Projection。
10. Phase 1 只定义 AthleteState 的稳定数据语义，不实现或虚构 Coaching Intelligence 算法。
11. AgentRuntime 不 import SQLAlchemy ORM，Reasoner 不 import Repository，ContextAssembler 不执行 SQL。
12. LLM、Capability 参数或 HTTP Body 都不能决定 `user_id`；身份只来自可信 `RequestContext`。
13. Capability 不读取 HTTP Request，只通过不可变 `CapabilityExecutionContext` 接收可信运行信息。
14. AthleteStateSnapshot、Workout 与 WorkoutFeedback 保持各自的数据语义，不混表、不互相冒充。
15. Memory 暂时为空但具有正式 `MemoryContextProvider` 接缝；Tool Runtime 暂未实现但通过 `CapabilityExecutor` Port 解耦。

任何实现如果违反上述规则，即使功能能够运行，也视为 Phase 1 未完成。

---

# 56. Phase 1 Implementation Order

建议按以下顺序落地：

```text
Step 1
Project Foundation
FastAPI / SQLAlchemy / Alembic / Config

Step 2
Identity
RequestContext / User Isolation

Step 3
Coaching Domain
Workout / Feedback / Goal / Plan / AthleteStateSnapshot

Step 4
Canonical Conversation + ConversationStore
Thread / Message / Turn / AgentRun / 双事务

Step 5
Lifecycle
Events / Owner / Dispatcher

Step 6
Context System
Providers / WorkingContext / ContextBundle

Step 7
Reasoner
Reasoner Port / ReasoningState / LLM Adapter / Action Model

Step 8
Capability Port
SimpleCapabilityExecutor

Step 9
Execution Trace + AgentRuntime
TraceRecorder / Reason → Action → Observation → Reason

Step 10
ChatService + FastAPI Endpoint

Step 11
Structured Logging / SSE Adapter

Step 12
Integration + Scenario Tests
```

不要先写 Agent Loop 再回头补数据模型和事务；先把状态所有权与生命周期边界建好。

---

# 57. Phase 1 Definition of Done

Phase 1 完成需要同时满足：

### Architecture

```text
模块依赖符合 ARCHITECTURE.md
无跨层 ORM 调用
Conversation / Runtime / Trace 边界清晰
ChatService / AgentRuntime ownership 清晰
```

### Domain

```text
Workout
WorkoutFeedback
Goal
Plan
AthleteStateSnapshot

模型与 Repository Port 可正常工作
不包含虚构的 AthleteState 算法
```

### Agent

```text
Thread
Message
Turn
ReasoningState
AgentRun
RunStep

三套状态各自按正式语义运行
```

### Context

```text
Working Context
Historical committed Conversation
Current input exactly once
Capability Context
Null Memory Context

统一通过 ContextAssembler 进入 Reasoner
```

### Runtime

```text
ContextBundle + ReasoningState
→ Capability Call
→ Observation
→ Reason
→ FinalAction
```

### Persistence & Lifecycle

```text
Transaction A 成功后 TurnStarted
Transaction B 成功后 TurnCommitted
Failed / Cancelled Turn 正确收尾
Message 与 RunStep 语义分离
call_id 正确关联调用与观察
```

### Tests

Integration Test 与 Scenario Test 覆盖关键链路并全部通过；仅对复杂纯逻辑和高风险状态转换保留必要 Unit Test。

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
  ↓
RequestContext
  ↓
ChatService
  ↓
ConversationStore.start_turn()
  ↓
Transaction A Commit
  ↓
TurnStarted
  ↓
AgentRuntime
  │
  ├── ContextAssembler
  │     ├── Working Context
  │     ├── Historical committed Conversation
  │     └── Memory Port（Null）
  │
  ├── Reasoner
  │     └── ReasoningState
  │
  ├── CapabilityExecutor
  │     └── Domain Application Service
  │
  └── TraceRecorder
        └── RunStep
  ↓
FinalAction
  ↓
ChatService
  ↓
ConversationStore.commit_turn()
  ↓
Transaction B Commit
  ↓
TurnCommitted
  ↓
Future Projectors
```

Phase 1 解决的不是“Run Coach 已经有多少功能”，而是：

> **任何新能力应该放在哪里、由谁拥有、通过什么接口进入 Agent、在什么生命周期修改状态。**

Phase 2 的 Tool Runtime、Phase 3 的 Coaching Intelligence、Phase 4 的 Memory 和 Phase 5 的 Eval 都应作为独立模块接入，不改变 Agent Core 的基本形态。

Phase 1 不实现弱化版 ToolRegistry，而是保留 `CapabilityExecutor` Port；不实现临时 pgvector Memory，而是保留 `MemoryContextProvider + TurnCommitted` 两个正式接缝。
