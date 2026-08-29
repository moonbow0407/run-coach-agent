# Run Coach Architecture

> **Status:** Active
> **Role:** Final Architecture Contract
> **Scope:** Run Coach 最终系统形态、模块职责、数据所有权、运行边界与不可破坏的架构约束

---

## 1. 文档职责

本文档定义 **Run Coach 最终应该是什么样的系统**。

它描述长期稳定的：

* 产品定位
* 系统边界
* 模块职责
* 数据所有权
* Agent Runtime
* Context
* Tool Runtime
* Coaching Intelligence
* Long-term Memory
* Event / Worker
* Persistence
* Security
* Observability
* Architectural Invariants

本文档**不描述当前开发进度，也不描述阶段性临时实现**。

阶段目标、实现顺序、阶段性 Adapter、验收标准由：

```text
docs/phases/PHASE_*.md
```

定义。

文档优先级为：

```text
ARCHITECTURE.md
        ↓
PHASE_*.md
        ↓
ADR / Module Documentation
        ↓
Code
```

如果当前代码与本文档冲突，应优先判断代码是否偏离最终架构，而不是为了兼容当前实现修改顶层设计。

---

# 2. Product Positioning

## 2.1 产品定位

Run Coach 是：

> **面向具有持续训练目标的业余跑者的长期自适应跑步教练 Agent。**

系统持续理解：

```text
训练事实
+
用户反馈
+
当前训练目标
+
训练计划
+
跑者状态
+
长期个人特征
+
历史相似经历
```

并在现实训练不断偏离原计划的情况下：

```text
Observe
   ↓
Understand
   ↓
Investigate
   ↓
Remember
   ↓
Decide
   ↓
Act
   ↓
Learn
```

形成长期训练闭环。

Run Coach 的核心价值不是生成一份计划，而是：

> **随着训练持续发生，持续回答“这个跑者现在怎么样，以及接下来应该怎么练”。**

---

## 2.2 要解决的核心问题

传统训练计划通常是静态的：

```text
生成计划
   ↓
按照计划训练
```

但真实训练环境是动态的：

```text
训练完成情况变化
身体状态变化
睡眠与恢复变化
训练反馈变化
时间安排变化
比赛目标变化
训练表现变化
```

因此：

```text
原始计划
```

会逐渐与：

```text
真实跑者状态
```

发生偏离。

Run Coach 要解决的是：

> **如何基于持续积累的真实证据理解这种偏离，并可靠地决定后续训练。**

---

## 2.3 Run Coach 不是什么

Run Coach 不是单纯的：

```text
Prompt
  ↓
LLM
  ↓
训练计划
```

也不是：

```text
通用 ChatBot
+
跑步 System Prompt
```

更不是单纯的：

```text
运动数据记录 App
```

Workout、心率、配速、距离等数据是系统进行判断的基础，但数据记录本身不是最终价值。

Run Coach 位于：

```text
Training Data Layer
        ↓
Running Intelligence
        ↓
Training Decision Layer
```

核心竞争力是：

> **Running Intelligence + Long-term Agent。**

---

# 3. Core Architecture Principle

整个系统建立在一个核心数据所有权原则之上：

> **PostgreSQL 保存发生过什么；Domain State 描述跑者现在怎么样；Memory 描述 Agent 长期如何理解这个人；Agent Runtime 根据当前目标自主调查证据、做出判断并执行能力。**

四者必须严格分离：

```text
Canonical Domain Facts
        │
        ▼
Derived Domain State

Canonical Conversation
        │
        ▼
Long-term Memory

        上述信息
           │
           ▼
     Agent Runtime
           │
           ▼
       Tool Runtime
           │
           ▼
        Action
```

不能将所有信息统一塞进：

```text
Prompt
Memory
Vector Database
```

然后交给模型自行解释。

---

# 4. System Architecture

Run Coach 采用：

> **模块化单体 + Worker**

而不是微服务架构。

整体结构：

```text
                            User
                              │
                   Text / Training Data
                              │
                              ▼
                         ┌─────────┐
                         │ Next.js │
                         └────┬────┘
                              │
                         HTTP / SSE
                              │
                              ▼
                    ┌───────────────────┐
                    │      FastAPI      │
                    │                   │
                    │ API / Identity    │
                    │ ChatService       │
                    │ Agent Runtime     │
                    │ Coaching Domain   │
                    │ Memory Retrieval  │
                    │ Tool Runtime      │
                    └────────┬──────────┘
                             │
             ┌───────────────┼────────────────┐
             │               │                │
             ▼               ▼                ▼
        PostgreSQL         Redis          Task Queue
                                               │
                                               ▼
                                         ┌──────────┐
                                         │  Worker  │
                                         └────┬─────┘
                                              │
                      ┌───────────────────────┼───────────────────────┐
                      ▼                       ▼                       ▼
               Memory Projection      Athlete State          Deep Analysis
                                      Recalculation
```

API Process 与 Worker Process 属于同一代码库和同一系统边界。

它们通过稳定的：

```text
Domain Model
Event Contract
Task Contract
Persistence Contract
```

协作。

---

# 5. Backend Modules

最终后端包含以下核心模块：

```text
run_coach
│
├── api
│
├── identity
│
├── coaching
│
├── agent
│
├── memory
│
├── tools
│
├── workers
│
├── evals
│
├── infrastructure
└── common
```

---

## 5.1 `api`

负责系统传输层：

```text
HTTP
SSE
Request Validation
Response Serialization
Dependency Wiring
```

API 不拥有核心业务规则。

禁止：

```text
Route
 ↓
直接操作 ORM
```

或者：

```text
Route
 ↓
直接实现训练算法
```

---

## 5.2 `identity`

负责：

```text
User Identity
Authentication
RequestContext
Authorization Boundary
```

用户身份必须在系统入口解析一次，并作为可信上下文沿执行链传播。

---

## 5.3 `coaching`

这是 Run Coach 最重要的领域模块。

负责：

> **Running Intelligence**

包括：

```text
Workout
Workout Feedback
Training Goal
Training Plan
Plan Change
Athlete State
Training Analysis
Plan Adaptation
```

Agent Framework 本身不是产品核心。

如果没有 Coaching Intelligence：

```text
Agent Runtime
Memory
Tool Runtime
```

只能形成一个通用 Agent 框架，而不能形成 Run Coach。

---

## 5.4 `agent`

负责：

```text
Conversation Lifecycle
Agent Run
Reasoning
Context Assembly
Runtime Working State
Execution Trace
Lifecycle Events
```

Agent 不拥有 Workout、Plan、Goal、Athlete State 等领域事实。

---

## 5.5 `memory`

负责：

```text
Semantic Memory
Episodic Memory
Evidence
Retrieval
Projection
Lifecycle
```

Memory 描述：

> **这个 Agent 长期如何理解这个用户，以及以前发生过哪些具有长期价值的经历。**

---

## 5.6 `tools`

负责 Agent 可以使用的能力系统：

```text
Tool Runtime
Tool Registry
Tool Search
Tool Session
Tool Resolver
Tool Executor
Builtin Tools
External Tools
```

Tool 是：

> **可被 Agent 调用的领域能力。**

而不是数据库 CRUD 的模型包装。

---

## 5.7 `workers`

负责不适合阻塞 HTTP / Agent 交互的异步任务：

```text
Memory Projection
Episode Projection
Athlete State Recalculation
Workout Deep Analysis
Embedding Generation
Eval Batch
Other Heavy Computation
```

---

## 5.8 `evals`

负责评估：

```text
Agent Decision Quality
Tool Selection
Coaching Quality
Safety
Regression
Trace Analysis
```

Eval 与生产 Runtime 解耦。

---

## 5.9 `infrastructure`

负责所有外部技术实现：

```text
PostgreSQL
Redis
Task Queue
LLM Provider
Authentication Adapter
External Integration
Observability
```

Domain / Agent Core 不直接依赖具体基础设施 SDK。

---

# 6. Coaching Domain

## 6.1 Canonical Domain Facts

以下对象表示业务事实：

```text
Workout
WorkoutFeedback
TrainingGoal
TrainingPlan
PlannedSession
PlanChange
```

这些事实属于 PostgreSQL 中的 Canonical State。

它们不能被 Memory 替代。

---

# 7. Workout

Workout 表示一次真实训练事实，例如：

```text
2026-08-27

10.2 km
55:32

avg pace 5:26
avg HR 158
max HR 176

type = tempo
```

核心语义：

```text
Workout

id
user_id

started_at

distance
duration

heart_rate

workout_type
source

created_at
```

训练数据可以来自：

```text
Manual Input
Imported Training Data
External Sports Platform
Device Data
Structured Multimodal Parsing
```

不同来源的数据必须首先经过：

```text
Input Adapter
      ↓
Normalization
      ↓
Validation
      ↓
Canonical Workout
```

之后才能进入 Coaching Domain。

外部数据格式不能渗透到核心领域模型。

---

# 8. Workout Feedback

WorkoutFeedback 表示：

> **用户关于一次训练明确报告的主观事实。**

例如：

```text
perceived_exertion
subjective_fatigue
soreness
note
```

必须明确区分：

```text
WorkoutFeedback.subjective_fatigue
=
用户说“我今天感觉很累”
```

和：

```text
AthleteStateSnapshot.fatigue_level
=
系统结合多种证据判断用户当前疲劳水平较高
```

前者是：

```text
Reported Fact
```

后者是：

```text
Derived State
```

两者绝不能混用。

---

# 9. Training Goal

TrainingGoal 表示训练目标：

```text
TrainingGoal

id
user_id

goal_type

race_date
race_distance
target_time

status

created_at
updated_at
```

同一用户可以拥有历史 Goal。

只有具有明确业务状态的 Goal 才能成为当前训练上下文。

---

# 10. Training Plan

TrainingPlan 必须是：

> **版本化的训练计划。**

结构：

```text
TrainingPlan

id
user_id

version
goal_id

status

starts_on
ends_on

created_at
```

计划包含：

```text
PlannedSession
```

例如：

```text
2026-09-01
Interval
6 × 1 km @ threshold pace
```

计划不能通过直接覆盖旧记录实现更新。

新的计划调整必须形成：

```text
Plan Version N
      ↓
Plan Change
      ↓
Plan Version N + 1
```

从而保留：

```text
历史计划
当时状态
修改原因
修改证据
最终结果
```

---

# 11. Plan Adaptation

Plan Adaptation 是 Run Coach 最重要的行动能力之一。

完整语义：

```text
Current Plan
     +
Latest Athlete State
     +
Recent Training Evidence
     +
Goal
     +
Relevant Memory
     ↓
Adaptation Decision
     ↓
PlanChange Proposal
     ↓
Domain Validation
     ↓
User Confirmation
     ↓
New Plan Version
     ↓
Activate
```

模型不能直接：

```text
UPDATE training_plan
```

Agent 只能通过正式领域能力提出修改。

任何会改变未来训练处方的 Plan Adaptation 都必须经过：

```text
Domain Validation
```

验证：

```text
计划完整性
日期合法性
训练结构
状态新鲜度
目标一致性
安全约束
版本一致性
```

对于具有真实副作用的计划修改：

> **生成建议与激活计划是两个不同动作。**

用户确认之前，不得把 Draft / Proposal 当成 Active Plan。

---

# 12. Athlete State

Athlete State 回答：

> **根据截至某个时间点能够获得的事实证据，系统认为这个跑者现在处于什么状态？**

它不是用户输入，也不是 Memory。

它属于：

> **Derived Domain State**

结构：

```text
AthleteStateSnapshot

id
user_id

version
as_of

fatigue_level
recovery_level

training_load
completion_rate

other validated running metrics

confidence

algorithm_version
created_at
```

---

## 12.1 Snapshot Semantics

Athlete State 必须保存为不可变版本化快照：

```text
Workout / Feedback / Plan
          ↓
   State Evaluator
          ↓
AthleteStateSnapshot V12

新的事实进入
          ↓
   State Evaluator
          ↓
AthleteStateSnapshot V13
```

禁止：

```text
不断 UPDATE 一行 current_state
```

导致历史判断依据消失。

---

## 12.2 `as_of`

每一个 AthleteStateSnapshot 必须具有：

```text
as_of
```

表示：

> 这份状态使用的事实证据截止到什么时间。

因此系统能够回答：

> “当时为什么建议我减少训练？”

而不是用今天的数据重新解释过去。

---

## 12.3 `algorithm_version`

状态计算必须记录：

```text
algorithm_version
```

不同版本算法产生的状态不能被视为完全相同的语义。

---

# 13. State 与 Fact 的关系

必须始终保持：

```text
Workout
WorkoutFeedback
TrainingPlan
      │
      │ Evidence
      ▼
AthleteStateSnapshot
```

不能反向：

```text
AthleteStateSnapshot
       ↓
覆盖 Workout / Feedback
```

系统推导永远不能篡改原始事实。

---

# 14. Long-term Memory

Long-term Memory 明确拆成：

```text
Long-term Memory
│
├── Semantic Memory
└── Episodic Memory
```

Memory 不包括：

```text
Workout
WorkoutFeedback
Goal
TrainingPlan
AthleteStateSnapshot
WorkingContext
ReasoningState
```

---

# 15. Semantic Memory

Semantic Memory 回答：

> **这个用户长期是什么样的人？**

例如：

```text
喜欢晚上训练

工作日早晨通常没有时间

不喜欢跑步机

更喜欢按距离而不是时间训练

连续两天高强度之后通常恢复较差
```

Semantic Memory 必须区分：

```text
Explicit
=
用户明确表达
```

和：

```text
Inferred
=
系统根据多次证据推断
```

建议核心结构：

```text
SemanticMemory

id
user_id

type
content

source_type
confidence

status

valid_from
valid_until

created_at
updated_at
```

---

# 16. Memory Evidence

任何 Memory 都必须能够追溯 Evidence。

例如：

```text
SemanticMemory

“用户周三晚上通常不能训练”
```

必须能够追溯：

```text
MemoryEvidence
      │
      └── Message
            │
            └── “这学期周三晚上都有课”
```

Evidence 可以来自：

```text
Message
Turn
Workout
WorkoutFeedback
AthleteStateSnapshot
PlanChange
Episode
Other Canonical Source
```

Memory 不能成为没有来源的模型结论数据库。

---

# 17. Semantic Memory Lifecycle

Semantic Memory 必须存在生命周期：

```text
candidate
    ↓
active
    ↓
superseded
    ↓
expired
```

例如：

```text
Memory A
“周三晚上有课”
status = active
```

后来用户说：

```text
“这学期周三晚上现在有空。”
```

应该形成：

```text
Memory A
status = superseded

Memory B
“周三晚上现在通常可以训练”
status = active
```

而不是删除历史认知。

---

# 18. Episodic Memory

Episodic Memory 回答：

> **以前发生过什么与当前情况类似的重要经历？**

例如：

```text
五月训练周期末出现疲劳积累

连续两周跑量上涨
        ↓
间歇训练失败
        ↓
主观疲劳增加
        ↓
主动降负荷
        ↓
一周后恢复
```

它不是：

```text
“用户容易疲劳”
```

这种 Semantic Fact。

它描述的是：

> **一段有时间范围、因果背景和后续结果的历史经历。**

核心结构：

```text
Episode

id
user_id

type
summary

started_at
ended_at

importance

embedding

created_at
```

关联：

```text
EpisodeEvidence
```

---

# 19. Episode 来源

Run Coach 的 Episode 不能只来源于聊天。

它可以由：

```text
Conversation
+
Workout
+
Workout Feedback
+
Athlete State
+
Plan Change
+
Race
```

共同形成。

例如：

```text
Episode

“第 5 周出现高负荷失配并成功降量恢复”
```

Evidence：

```text
Workout #201
Workout #203
Feedback #88
AthleteState #51
PlanChange #17
```

这是垂直领域 Agent 相比通用 Chat Memory 的关键能力。

---

# 20. Working Context

长期 Memory 与当前 Context 必须分离。

每次 Agent Run 开始时，ContextAssembler 动态形成：

```text
WorkingContext
```

包含高频且高度相关的当前信息，例如：

```text
Current Goal
Current Training Plan
Current Training Block
Latest Athlete State
Critical Constraints
```

WorkingContext：

```text
不独立拥有数据
不承担长期存储
不等于 Memory
```

它只是：

> **本次 Agent Run 的 Hot Context。**

---

# 21. Agent State Model

系统必须明确分离三套状态：

```text
Conversation State

Thread
Message
Turn
```

```text
Runtime Working State

ReasoningState
```

```text
Execution Trace

AgentRun
RunStep
```

它们分别回答三个完全不同的问题。

---

## 21.1 Conversation State

回答：

> 用户真正经历了什么？

包含：

```text
Thread
Message
Turn
```

`Message` 只保存：

```text
user
assistant
```

实际形成的 Canonical Conversation。

禁止把：

```text
Tool Call
Observation
Internal Reasoning
Model Request
Internal Tool State
```

伪装成普通 Message 保存。

---

## 21.2 ReasoningState

回答：

> **当前 AgentRun 内，Agent 已经执行和观察了什么？**

包含：

```text
ToolCallAction
Observation
```

ReasoningState：

```text
只存在于当前 AgentRun 生命周期
```

不得承担长期持久化事实的职责。

不得保存隐藏 Chain of Thought。

---

## 21.3 Execution Trace

回答：

> **Agent 当时实际上如何完成这个任务？**

结构：

```text
AgentRun
   │
   ├── RunStep
   ├── RunStep
   └── RunStep
```

记录：

```text
Reasoning Boundary
Tool Call
Observation
Final Action
Timing
Status
Error
```

Tool Call 与 Observation 应通过：

```text
call_id
```

关联。该 `call_id` 是 Runtime 生成的内部 UUID，与模型 native tool calling 协议 ID（`model_call_id`）分离。

Execution Trace 用于：

```text
Debug
Observability
Eval
Audit
Regression Analysis
```

而不是作为 Agent Runtime 的工作记忆。

---

# 22. ChatService 与 AgentRuntime

ChatService 和 AgentRuntime 的 ownership 必须严格分开。

---

## 22.1 ChatService

ChatService 是：

> **一次用户交互的 Application Orchestrator。**

负责：

```text
Thread
Message
Turn
AgentRun

Start
Commit
Fail
Cancel
```

以及 Conversation 的事务边界。

---

## 22.2 AgentRuntime

AgentRuntime 只负责：

```text
Context
   ↓
Reason
   ↓
Action
   ↓
Observation
   ↓
Reason
   ↓
Final
```

AgentRuntime 不负责：

```text
创建 Thread
创建 Turn
提交 Conversation
直接操作 ORM
Authentication
Memory Projection
HTTP
SSE
```

---

# 23. Agent Execution Flow

标准执行链：

```text
User Request
     ↓
Authentication
     ↓
RequestContext
     ↓
ChatService
     ↓
Start Turn + AgentRun
     ↓
AgentRuntime
     │
     ├── ContextAssembler → ContextBundle
     │
     ├── ToolRuntime.create_session
     │
     └── Reasoner（ContextBundle + ReasoningState + 当前可见 Tool）
               ↓
            Action
               │
               ├── FinalAction
               │
               └── ToolCallAction
                         ↓
                    ToolRuntime.execute
                         ↓
                    Observation
                         ↓
                    ReasoningState
                         ↓
                      Reasoner
                         ↓
                        ...
                         ↓
                    FinalAction
     ↓
ChatService Commit
     ↓
TurnCommitted
```

`ChatService` 拥有 Turn / AgentRun 生命周期。`AgentRuntime` 拥有单次 Run 的推理循环，并在循环内调用 `ContextAssembler` 与 `ToolRuntime`。`ContextAssembler` 不调用 `AgentRuntime`。

模型可以自主决定：

```text
是否需要工具
调用哪个工具
调用顺序
是否已有足够证据
何时形成最终回答
```

禁止使用大量：

```text
if intent == ...
```

把 Agent Runtime 重新写成固定 Workflow。

---

# 24. Runtime Boundaries

Agent Runtime 可以具有：

```text
最大运行步数
超时
取消
错误边界
资源预算
```

这些属于：

> **Runtime Protection**

而不是固定业务流程。

保护机制用于防止：

```text
无限循环
异常工具调用
资源失控
无终止推理
```

但不能规定：

```text
第 1 步必须调用 A
第 2 步必须调用 B
最多只能追问固定次数
```

Agent 的任务策略应由当前证据决定。

---

# 25. Context System

Reasoner 不能直接读取整个数据库。

统一通过：

```text
ContextAssembler
```

形成：

```text
ContextBundle

System Instructions

Working Context

Historical Committed Conversation

Retrieved Semantic Memory

Retrieved Episodes

Current User Input
```

`ContextBundle` 不包含 Tool Schema。可见 Tool 不属于 Context Assembly，而由 Tool Runtime 在每轮推理时单独解析。

---

## 25.1 Context Provider Boundary

ContextAssembler 不直接执行：

```text
SQL
Vector Search
Domain Calculation
External API
Tool Registry Lookup
```

而依赖 Provider：

```text
WorkingContextProvider
ConversationContextProvider
MemoryContextProvider
```

因此：

```text
ContextAssembler
=
决定 Context 由什么组成
```

而：

```text
Provider
=
负责如何获取对应数据
```

ContextAssembler 不管理 Tool；可见 Tool 不通过 Context Provider 注入。

---

## 25.2 Conversation Context

历史 Conversation 必须只包含：

```text
committed Turn
```

中的：

```text
user / assistant Message
```

当前用户输入：

```text
ContextBundle.current_input
```

只能出现一次。

如果当前 User Message 已经为了事务可靠性写入数据库，它仍必须从：

```text
recent_messages
```

中排除。

Failed / Cancelled Turn 不得污染正常 committed Conversation Context。

---

## 25.3 ReasoningContext 与 Tool 可见性

每轮推理的输入是 `ReasoningContext`，由三部分组成：

```text
稳定的 ContextBundle
+
当前 AgentRun 的 ReasoningState
+
当前 ToolResolver 解析出的可见 Tool Definition
```

可见 Tool 每轮重新计算，规则为当前仍注册的 always-on Tool 与当前仍注册且已在本 AgentRun 内发现的 Tool 的并集。

因此：

```text
Registered ≠ Visible ≠ Executable
```

模型猜到但尚未对本 Session 可见的 Tool 不得执行。一次 AgentRun 中发现的 Tool 只属于该 Run 的 ToolSession，不得进入 ContextBundle，也不得污染后续 Turn。

---

# 26. Prompt Rendering

Context Assembly 与 Prompt Rendering 必须分离：

```text
ContextAssembler
      ↓
ContextBundle
      +
ReasoningState
      +
Visible Tools
      ↓
PromptRenderer
      ↓
ModelRequest
```

ContextAssembler 回答：

> 给模型哪些稳定上下文？

PromptRenderer 回答：

> 这些信息以及当前可见 Tool 如何表达给模型？

`ModelRequest` 由 provider-neutral 消息与本轮动态 Tool Definition 组成。Tool Schema 只作为 native tool calling 的 tools 传入，不得写入 system prompt、输出 JSON Contract 或固定 Workflow。供应商协议只存在于 LLM Provider Adapter。

PromptRenderer 不读取：

```text
ORM
Repository
RunStep
ToolRegistry
```

也不保存隐藏 Chain of Thought。

---

# 27. Reasoner

AgentRuntime 依赖：

```text
Reasoner
```

而不是具体模型 SDK。

结构：

```text
AgentRuntime
      ↓
Reasoner
```

LLM 实现：

```text
LLMReasoner
      ↓
LLMProvider
```

Reasoner 接收 `ReasoningContext`，只把模型响应转换为统一 Action：

```text
ToolCallAction
FinalAction
```

供应商 native tool calling 协议封装在 LLM Provider Adapter 内。Reasoner 不访问 Registry、Search、Executor、Application Service 或 Repository。

这样 Runtime 可以使用：

```text
LLMReasoner
ScriptedReasoner
FakeReasoner
Future Hybrid Reasoner
```

而无需改变 Agent Core。

---

# 28. Tool Runtime

最终 Tool Runtime：

```text
ToolRuntime
│
├── Tool
├── ToolRegistry
├── ToolSearch          （Registry 的派生检索状态）
├── ToolSession         （每个 AgentRun 一份，含 Run-local Discovery）
├── ToolResolver
└── ToolExecutor
```

AgentRuntime 只通过 `ToolRuntime` 创建 Session、解析当前可见 Tool 并执行 `ToolCallAction`。Registry、Search、Resolver、Executor 与参数模型的细节不得泄漏进 Reason–Act–Observe 主循环。

系统必须始终区分：

```text
Registered
≠
Visible
≠
Executable
```

- Registered：Tool 存在于 Registry
- Visible：完整 Schema 当前被提供给 Reasoner
- Executable：仍在 Registry、当前 Session 可见、参数有效且通过执行治理

---

## 28.1 Tool Registry

回答：

> 系统拥有哪些可执行能力？

保存：

```text
Tool Definition
Executable
Metadata
Schema
Risk
Source
Search Document
```

Registry 是 Tool 存在性的唯一事实来源。已经发现但随后注销的 Tool 必须立即从 Resolver 与 Executor 中消失。

---

## 28.2 Tool Search

回答：

> 当前任务可能需要哪些尚未可见的能力？

Tool 数量增长后，不能无条件将整个工具集塞给模型，也不能把全部 Schema 放入 `ContextBundle`。

Search Index 是 Registry 的派生状态，而不是独立的 Source of Truth。搜索只返回候选名称与简要描述，不能绕过 Resolver 直接执行。长期 Catalog / 语义检索可以在此边界上演进，但不能把 Tool 所有权搬出 Registry。

---

## 28.3 Tool Resolver 与 ToolSession

Resolver 负责将当前 Session 解析成：

```text
当前 Reasoner 可以看到的 Tool Schema
```

每个 AgentRun 创建独立 `ToolSession`，内部持有 `run_id` 与 Run-local Discovery。Discovery 只保存当前 Run 通过搜索获得的 Tool 名称，不写入 Conversation / Memory，也不跨 Turn 复用。AgentRun 结束后 Session 销毁。

可见集合每轮重新计算：当前仍注册的 always-on Tool ∪ 当前仍注册且已发现的 Tool。

---

## 28.4 Tool Executor

负责：

```text
Existence
Session Visibility
Authorization
Argument Validation
Trusted ToolExecutionContext
Execution
Timeout
Error Normalization
Result Validation
Observation
```

模型只能提供业务参数。身份、所有权、执行归属与链路追踪字段由 Runtime 注入，不得出现在 Tool 参数模型中。

---

# 29. Tools Express Domain Abilities

Tool 应表达领域能力：

```text
Training Data
├── get_recent_workouts
├── get_workout_detail
└── analyze_workout

Athlete State
├── get_athlete_state
├── analyze_training_load
└── analyze_training_trend

Training Plan
├── get_active_plan
├── inspect_training_block
└── adapt_training_plan

Memory
├── recall_semantic_memory
└── recall_episode

External
├── get_weather
└── search_race
```

不应该把：

```text
SQL
Repository
CRUD
```

直接暴露给模型。

模型调用：

```text
analyze_training_load
```

而不是：

```text
SELECT workouts ...
```

---

# 30. Trusted ToolExecutionContext

模型生成的 Tool Arguments 与可信运行信息必须严格分离。

模型参数：

```json
{
  "days": 14
}
```

Runtime 提供：

```text
user_id
thread_id
turn_id
run_id
call_id
request_id
trace_id
timestamp
```

形成：

```text
Model Arguments
       +
Trusted ToolExecutionContext
       ↓
ToolExecutor
```

禁止模型通过参数决定：

```text
user_id
authorization
run_id
permission
```

等可信信息。

---

# 31. Identity Boundary

用户身份只能来自：

```text
Authentication
      ↓
RequestContext
```

禁止从：

```text
HTTP Body
LLM Output
Tool Arguments
Prompt
```

决定 `user_id`。

所有用户数据访问都必须受到：

```text
user_id
```

约束。

这是系统最重要的数据隔离边界之一。

---

# 32. Mutation and Side Effects

Tool 必须区分：

```text
Read
Analyze
Draft
Mutate
External Side Effect
```

高风险副作用不能因为模型输出了一个 Tool Call 就自动执行。

特别是：

```text
Training Plan Mutation
```

必须经过：

```text
Proposal
Validation
Freshness Check
Confirmation
Activation
```

Reasoning 与副作用执行必须保持可审计边界。

---

# 33. Freshness and Optimistic Concurrency

Agent 做出修改时使用的状态可能在推理过程中发生变化。

因此涉及状态修改的 Action 必须携带必要的：

```text
based_on_plan_version
based_on_state_version
other expected versions
```

执行前再次检查：

```text
Expected Version
      ==
Current Version
```

否则拒绝修改，并要求重新读取最新状态。

禁止：

```text
基于旧 Athlete State
       ↓
覆盖最新 Training Plan
```

---

# 34. Idempotency

所有具有副作用的用户操作或 Tool Action 都必须考虑幂等。

典型场景：

```text
网络重试
SSE 重连
客户端重复提交
Worker 重试
Queue Redelivery
模型重复调用 Tool
```

不能导致：

```text
重复创建计划
重复确认
重复写入训练
重复执行外部副作用
```

幂等边界应由 Application / Tool Runtime / Domain 明确定义，而不是依赖模型“不重复调用”。

---

# 35. Memory Retrieval

Memory Retrieval 必须分开处理：

```text
Semantic Retrieval
```

回答：

> 这个用户有哪些与当前问题相关的长期特征？

和：

```text
Episodic Retrieval
```

回答：

> 以前有没有发生过类似情况？

当前事实则由：

```text
Working Context
+
Domain Tools
```

提供。

最终 Reasoner 获得：

```text
Current Facts
+
Current State
+
Long-term Knowledge
+
Historical Experience
```

而不是混成一个不可解释的 Memory Blob。

---

# 36. Memory Learning Boundary

Memory Retrieval 与 Memory Learning 必须严格分离。

禁止：

```text
Agent 正在 Reasoning
      ↓
随手修改长期 Memory
```

正确路径：

```text
User Input
    ↓
Agent Run
    ↓
Final Response
    ↓
Conversation Commit
    ↓
TurnCommitted
    ↓
Memory Projection
```

只有已提交、可追溯的事实才能成为长期 Memory 的输入。

失败、取消或未提交的 Turn 不得污染长期 Memory。

---

# 37. Event Architecture

Run Coach 使用事件解耦：

```text
Domain State
Projection
Memory Learning
Async Processing
Eval Collection
```

但系统：

> **不采用 Event Sourcing 作为主要持久化模型。**

PostgreSQL 中的业务表仍然是 Canonical State。

Event 用于：

> 解耦已经发生的事实与后续反应。

典型事件：

```text
WorkoutImported
WorkoutAnalyzed

WorkoutFeedbackSubmitted

AthleteStateUpdated

PlanCreated
PlanAdapted

TurnCommitted
```

---

# 38. Projection Separation

不同 Projection 必须拥有明确职责。

例如：

```text
WorkoutImported
      ↓
AthleteState Projector
```

回答：

> 这次训练对当前跑者状态意味着什么？

而：

```text
TurnCommitted
      ↓
Memory Projector
```

回答：

> 这次交互是否产生值得长期记住的信息？

二者不能合并为一个万能：

```text
MemoryUpdater
```

---

# 39. Reliable Event Delivery

对于会驱动重要异步 Projection 的事件：

```text
DB State
+
Event Delivery
```

必须避免永久不一致。

例如：

```text
Training Plan COMMIT
        ↓
Process Crash
        ↓
PlanAdapted Event 永久丢失
```

最终系统应通过可靠事件交付机制保证关键 Post-Commit 工作可以恢复，例如：

```text
Transactional Outbox
+
Durable Queue
+
Idempotent Consumer
```

具体 Queue 技术属于 Infrastructure Decision，不属于 Domain Contract。

---

# 40. Worker

Worker 与 API 使用相同 Domain Contract。

Worker 适合执行：

```text
memory_projection
episode_projection

athlete_state_recompute

workout_deep_analysis

embedding_generation

eval_batch
```

Worker 不应该重新实现一套独立业务逻辑。

结构：

```text
Task
  ↓
Application Service
  ↓
Domain
  ↓
Repository
```

而不是：

```text
Task
  ↓
直接 SQL
```

---

# 41. PostgreSQL

PostgreSQL 是系统长期 Canonical Persistence。

逻辑边界：

```text
identity.*

users
auth...
```

```text
coaching.*

workouts
workout_feedback

training_goals

training_plans
planned_sessions
plan_changes

athlete_state_snapshots
```

```text
agent.*

threads
messages
turns

agent_runs
run_steps
```

```text
memory.*

semantic_memories
memory_evidence

episodes
episode_evidence
```

这些是：

> **逻辑 Schema Boundary**

并不要求物理数据库一定创建同名 PostgreSQL Schema。

---

# 42. Redis

Redis 只承担短生命周期状态：

```text
SSE Run State

Rate Limit

Short-lived Cache

Distributed Lock

Task Progress

Ephemeral Coordination
```

禁止把 Redis 作为：

```text
Canonical Workout Store
Canonical Training Plan
Long-term Memory Store
Athlete State Source of Truth
```

长期事实最终以 PostgreSQL 为准。

---

# 43. Data Source of Truth

必须明确以下数据所有权：

```text
Workout
WorkoutFeedback
Goal
Plan
PlanChange
        ↓
PostgreSQL Canonical Domain Facts
```

```text
AthleteStateSnapshot
        ↓
PostgreSQL Versioned Derived State
```

```text
Semantic / Episodic Memory
        ↓
PostgreSQL Long-term Agent Knowledge
```

```text
ReasoningState
        ↓
Current AgentRun Memory Only
```

```text
Redis
        ↓
Short-lived Operational State
```

模型 Context 永远不是 Source of Truth。

---

# 44. Transaction Boundary

数据库事务不能跨越：

```text
LLM Call
External Tool
Long-running Tool
```

一次用户交互应保持短事务。

典型结构：

```text
Transaction A
Start Turn
Persist User Message
Create AgentRun
COMMIT

        ↓

Agent Runtime
Reason / Tool / Observation
No long DB transaction

        ↓

Transaction B
Persist Assistant Message
Commit Turn
Complete AgentRun
COMMIT

        ↓

TurnCommitted
```

这样避免：

```text
LLM 延迟
       ↓
长事务
       ↓
连接池占用
锁等待
失败回滚范围过大
```

---

# 45. Failure Semantics

Agent 执行失败时：

```text
Turn = failed
AgentRun = failed
```

已经保存的 User Message 可以作为失败交互事实保留。

但不能产生：

```text
Committed Assistant Message
TurnCommitted
Memory Projection
```

Infrastructure Exception 必须经过系统边界归一化。

禁止向：

```text
LLM
Frontend
Observation
```

直接暴露数据库连接串、内部堆栈或其他敏感基础设施信息。

---

# 46. Cancellation Semantics

Agent Run 被取消时：

```text
Turn = cancelled
AgentRun = cancelled
```

Runtime 负责：

```text
停止 Reasoning
停止正在执行的 Tool
释放资源
传播 Cancellation
```

ChatService 负责：

```text
Conversation 状态持久化
```

取消交互不能形成正常 committed Conversation，也不能进入长期 Memory Projection。

---

# 47. Lifecycle

Lifecycle Event 必须具有明确 Owner。

Conversation Lifecycle：

```text
ChatService
```

Agent Execution Lifecycle：

```text
AgentRuntime
```

典型事件：

```text
TurnStarted

ContextAssemblyStarted
ContextAssembled

ReasoningStarted
ReasoningCompleted

ToolStarted
ToolCompleted

TurnCommitStarted
TurnCommitted

TurnFailed
TurnCancelled
```

同一个 Lifecycle Event 只能拥有一个 Publisher Owner。

---

# 48. SSE

SSE 是 Lifecycle 的 Adapter，而不是 Agent Runtime 的职责。

结构：

```text
Agent Runtime
      ↓
Lifecycle Event
      ↓
SSE Adapter
      ↓
Frontend
```

而不是：

```text
AgentRuntime
      ↓
直接 send SSE
```

Tool 执行进度映射为 `tool.started` / `tool.completed`；不新增 ToolDiscovered 事件，Discovery 以 Tool Call / Observation Trace 为详细记录。ToolRuntime 不直接发送 SSE。

这样未来可以让同一 Lifecycle 同时驱动：

```text
SSE
Logging
Metrics
Trace
Eval
```

---

# 49. LLM Boundary

具体模型 SDK 必须隐藏在：

```text
LLMProvider
```

后面。

结构：

```text
AgentRuntime
      ↓
Reasoner
      ↓
LLMReasoner
      ↓
LLMProvider
      ↓
Model Vendor
```

禁止核心 Domain / Runtime 直接依赖具体：

```text
OpenAI SDK
Anthropic SDK
Gemini SDK
其他模型 SDK
```

模型可以替换，而 Agent Runtime 与 Domain Contract 不应因此重写。

LLMProvider 负责把 provider-neutral 消息与本轮动态 Tool Definition 翻译为供应商 native tool calling 协议。AgentRuntime 与 Reasoner 只认识统一的 `ToolCallAction`、`Observation` 与 `FinalAction`。不支持 native tool calling 的模型配置必须 fail fast，不得退回文本 JSON Action Contract。

---

# 50. Safety Boundary

Run Coach 是训练决策系统，不是医疗诊断系统。

系统可以：

```text
识别异常训练表现
识别恢复不足信号
降低训练风险
建议减少或停止训练
建议寻求专业帮助
```

但不得把模型判断包装成确定医疗诊断。

当存在明显高风险信息时：

```text
Safety Constraint
```

优先级高于：

```text
训练目标
比赛计划
用户短期成绩诉求
```

Safety Rules 属于确定性系统约束，不能完全依赖 Prompt。

---

# 51. Explainability

重要训练建议必须能够回答：

> 为什么？

尤其是：

```text
降低跑量
取消强度
增加恢复
调整比赛目标
修改训练计划
```

最终判断应能够追溯到：

```text
Workout Evidence
Feedback Evidence
Athlete State Version
Plan Version
Relevant Memory
Relevant Episode
```

系统不能只保存：

```text
“模型觉得应该降量”
```

---

# 52. Observability

每一次用户 Agent 执行至少贯穿：

```text
request_id
trace_id
user_id
thread_id
turn_id
run_id
```

每次 Tool Call additionally 包含：

```text
call_id
```

通过 `run_id` 必须能够关联：

```text
Conversation
Lifecycle
Reasoning Boundary
Tool
Observation
Error
Latency
Final Result
```

---

# 53. Eval Architecture

Eval 不是额外 Demo，而是 Agent 系统质量保障的一部分。

Eval 可以消费：

```text
Conversation
AgentRun
RunStep
Tool Result
Domain State
Expected Scenario
```

评估：

```text
Tool Selection Correctness

Evidence Usage

Hallucination

Coaching Decision Quality

Plan Adaptation Quality

Safety

User Data Isolation

Regression
```

测试不能只验证：

```text
HTTP 200
```

而必须验证：

```text
Context
→ Reason
→ Tool
→ Observation
→ Decision
→ Side Effect
```

是否符合正式语义。

---

# 54. Recommended Final Directory Boundary

最终代码模块边界：

```text
backend/
├── app/
│
│   ├── api/
│   │   ├── routes/
│   │   ├── dependencies/
│   │   ├── schemas/
│   │   └── sse/
│   │
│   ├── identity/
│   │   ├── domain/
│   │   ├── application/
│   │   └── ports/
│   │
│   ├── coaching/
│   │   ├── domain/
│   │   │   ├── workout/
│   │   │   ├── goal/
│   │   │   ├── plan/
│   │   │   └── athlete/
│   │   │
│   │   ├── application/
│   │   └── ports/
│   │
│   ├── agent/
│   │   ├── application/
│   │   ├── models/
│   │   ├── runtime/
│   │   ├── reasoning/
│   │   ├── context/
│   │   ├── lifecycle/
│   │   └── ports/
│   │
│   ├── memory/
│   │   ├── semantic/
│   │   ├── episodic/
│   │   ├── retrieval/
│   │   ├── projection/
│   │   ├── models/
│   │   └── ports/
│   │
│   ├── tools/
│   │   ├── registry/
│   │   ├── search/
│   │   ├── resolver/
│   │   ├── executor/
│   │   └── builtin/
│   │
│   ├── workers/
│   │
│   ├── evals/
│   │
│   ├── infrastructure/
│   │   ├── auth/
│   │   ├── database/
│   │   ├── cache/
│   │   ├── queue/
│   │   ├── llm/
│   │   ├── integrations/
│   │   └── observability/
│   │
│   └── common/
│
├── migrations/
├── tests/
└── scripts/
```

这个目录表达的是长期模块边界。

不应该为了匹配目录图而提前创建没有实际实现的空目录或空抽象。

---

# 55. Full System Loop

Run Coach 最终的核心业务闭环：

```text
                      Runner
                        │
              Workout / Feedback
                        │
                        ▼
                Canonical Facts
                        │
             ┌──────────┴──────────┐
             │                     │
             ▼                     ▼
     Athlete State            Domain Events
       Evaluator                   │
             │                     │
             ▼                     ▼
   AthleteStateSnapshot       Async Projectors
             │
             │
             ▼
      Working Context
             │
             ├────────────────────────────┐
             │                            │
             ▼                            ▼
      Agent Runtime               Memory Retrieval
             │                    │              │
             │                    ▼              ▼
             │                Semantic        Episodic
             │                 Memory          Memory
             │                    │              │
             └────────────┬───────┴──────────────┘
                          ▼
                       Reasoner
                          │
                          ▼
                      Tool Runtime
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
       Training Data   State       Training Plan
          Tools        Tools           Tools
             │            │            │
             └────────────┼────────────┘
                          ▼
                   Domain Services
                          │
                          ▼
                 Coaching Decision
                          │
                          ▼
                 PlanChange Proposal
                          │
                   Validation / Confirm
                          │
                          ▼
                   New Plan Version
                          │
                          ▼
                    Future Workout
                          │
                          └───────────────┐
                                          │
                                          ▼
                                      Learn Again
```

真正的产品闭环是：

```text
Observe
→ Understand
→ Investigate
→ Remember
→ Decide
→ Act
→ Learn
→ Observe Again
```

而不是一次性的：

```text
User
→ LLM
→ Answer
```

---

# 56. Example End-to-End Scenario

用户：

> 昨天那个间歇跑崩了，最后两组完全跑不动，今天腿也挺酸，这周后面怎么练？

系统首先装配：

```text
Current Goal
Current Plan
Latest Athlete State
Critical Constraints
Relevant Memories
Relevant Episodes
Recent Conversation
```

Reasoner 判断当前证据不足：

```text
get_workout_detail(yesterday)
        ↓
Observation

get_recent_workouts()
        ↓
Observation

analyze_training_load()
        ↓
Observation

get_active_plan()
        ↓
Observation
```

形成判断：

```text
近期训练负荷持续上升

关键训练完成质量下降

主观疲劳和酸痛增加

当前计划仍包含高负荷课次
```

随后：

```text
adapt_training_plan
        ↓
PlanChange Proposal
        ↓
Domain Validation
        ↓
向用户解释调整依据
        ↓
User Confirmation
        ↓
New Plan Version
```

Turn 成功提交后：

```text
TurnCommitted
      │
      └── Memory Projection

PlanAdapted
      │
      └── Episode Projection

Workout / Feedback
      │
      └── Athlete State Recalculation
```

后续训练结果再验证这次判断。

这才是 Run Coach 的完整长期闭环。

---

# 57. Architectural Invariants

以下规则属于 Run Coach 的长期架构不变量。

任何实现即使能够工作，只要违反这些规则，就视为架构偏离。

1. **Canonical Facts、Derived State、Long-term Memory 与 Runtime State 必须分离。**

2. **Workout、WorkoutFeedback、Goal、TrainingPlan 等领域事实以 PostgreSQL 为 Source of Truth，不能由 Memory 替代。**

3. **AthleteStateSnapshot 是系统推导状态，必须版本化并具有明确 `as_of` 与算法版本。**

4. **WorkoutFeedback 中用户报告的主观状态不能冒充 Athlete State。**

5. **Conversation State、ReasoningState 与 Execution Trace 必须分离。**

6. **Message 只保存 user / assistant Canonical Conversation。**

7. **Tool Call 与 Observation 属于 Runtime / Trace，不属于普通 Conversation Message。**

8. **ReasoningState 与 Tool Discovery 只属于当前 AgentRun：不保存隐藏 Chain of Thought，不作为长期 Canonical State，也不跨 Turn 复用。**

9. **AgentRuntime 不通过读取历史 RunStep 驱动正常 Reasoning。**

10. **ChatService 拥有 Conversation 生命周期与事务边界；AgentRuntime 只负责 Context → Reason → Action → Observation → Final。**

11. **ContextAssembler 不直接执行 SQL、Vector Search 或领域计算，也不装配 Tool。可见 Tool 由 Tool Runtime 每轮解析并进入 ReasoningContext，不进入 ContextBundle。**

12. **当前 User Input 在 Context 中只出现一次；Conversation Context 只包含历史 committed Turn。**

13. **用户身份只能来自可信 RequestContext，不能来自 HTTP Body、LLM Output 或 Tool Arguments。**

14. **ToolExecutionContext 与模型生成的 Tool Arguments 必须分离。**

15. **Tool 必须表达领域能力，而不是直接向模型暴露 Repository / SQL / CRUD。**

16. **具有副作用的 Tool 必须经过授权、参数校验、状态新鲜度检查和领域规则校验。**

17. **Training Plan 必须版本化；不得通过覆盖旧计划丢失历史。**

18. **Plan Adaptation 的 Proposal、Validation、Confirmation 与 Activation 必须保持独立语义。**

19. **基于旧 Plan / Athlete State 的修改不得覆盖更新版本。**

20. **具有副作用的操作必须设计幂等边界，不能依赖模型避免重复执行。**

21. **Memory 必须具有 Evidence；模型推断不能成为无来源的长期事实。**

22. **Memory Retrieval 与 Memory Projection 必须分离。**

23. **只有 committed Conversation 与正式 Domain Facts 可以驱动长期 Memory Learning。**

24. **Memory Projector 与 Athlete State Projector 必须保持独立职责。**

25. **Redis 只保存短生命周期 Operational State，不承担长期事实所有权。**

26. **数据库事务不得跨越 LLM、外部 Tool 或其他不可控长耗时操作。**

27. **关键 Post-Commit Projection 必须支持可靠恢复与幂等重放。**

28. **LLM Provider、Queue、Redis、Database Driver 等具体基础设施不能渗透进 Agent / Coaching Domain Core。**

29. **Safety Constraint 的优先级高于训练目标与成绩优化。**

30. **重要训练决策必须能够追溯其主要事实依据、状态版本和计划版本。**

31. **系统不得为了展示 Agent 技术复杂度而牺牲 Running Intelligence 的领域边界。**

32. **所有架构扩展最终都必须服务于一个目标：让系统更可靠地理解“这个跑者现在怎么样，以及接下来应该怎么练”。**

---

# 58. Final Principle

Run Coach 的最终形态不是：

```text
一个会调用工具的跑步 ChatBot
```

而是：

> **一个以长期跑者数据和状态为基础，能够持续观察、理解、调查、记忆、决策、行动并从后续训练中学习的自适应训练系统。**

其中：

```text
Coaching Domain
=
系统理解跑步训练的能力
```

```text
Athlete State
=
系统理解跑者当前状态的能力
```

```text
Memory
=
系统长期理解这个人的能力
```

```text
Agent Runtime
=
系统自主调查和决策的能力
```

```text
Tool Runtime
=
系统可靠执行行动的能力
```

```text
Worker / Event
=
系统持续学习和投影状态的能力
```

最终所有模块共同形成：

```text
Long-term Adaptive Running Coach
```

这就是 Run Coach 的架构终点。
