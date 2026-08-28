可以。我们这次把它当成 **Run Coach  全新系统**，从产品目标和数据所有权开始设计，不继承“最多几轮工具调用、几次追问”之类旧约束。

我建议第一版架构先定一个非常核心的原则：

> **PostgreSQL 保存跑者真实发生过的事情；Domain State 描述跑者现在怎么样；Memory 描述 Agent 长期如何理解这个人；Agent Runtime 根据当前目标自主调用能力完成判断和行动。**

这四个东西一定要分开。

# Run Coach  Architecture v0.1

> Status: Active

## 1. 系统目标

我们要做的不是：

```text
用户输入
→ Prompt
→ LLM
→ 生成训练计划
```

而是一个长期运行闭环：

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

对应到跑步场景：

```text
用户完成训练 / 提供反馈
        ↓
系统理解发生了什么
        ↓
更新跑者状态
        ↓
Agent 判断是否存在问题
        ↓
主动查询训练历史 / 当前计划 / 长期记忆
        ↓
给出建议或调整计划
        ↓
后续训练继续验证判断
```

------

# 2. 我建议采用「模块化单体 + Worker」

现阶段完全没必要拆微服务。

整体：

```text
                         Next.js
                            │
                      HTTP / SSE
                            │
                            ▼
                  ┌──────────────────┐
                  │     FastAPI      │
                  │                  │
                  │  API / Auth      │
                  │  Agent Runtime   │
                  │  Domain Service  │
                  │  Tool Runtime    │
                  └────────┬─────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
     PostgreSQL          Redis        Task Queue
          │                                 │
          │                                 ▼
          │                              Worker
          │                                 │
          └─────────────────────────────────┘
```

代码仍然是一套项目，只是部署两个 Python Runtime：

```text
API Process
Worker Process
```

API 负责：

```text
请求
Agent 交互
轻量查询
SSE
```

Worker 负责：

```text
Memory 投影
训练状态重计算
批量训练分析
Eval
耗时模型调用
```

这比一上来拆五六个 service 更适合作品项目，也更容易讲清架构。

------

# 3. 整个后端分成五个核心层

我会这样划：

```text
run_coach
│
├── agent
│
│   └── Agent Runtime / Reasoning
│
├── coaching
│   └── 跑步领域能力
│
├── memory
│   └── 长期认知
│
├── tools
│   └── Agent 能力系统
│
└── infrastructure
    └── DB / Redis / Queue / LLM
```

外加两个横切模块：

```text
identity
evals
```

------

# 4. 第一层：Coaching Domain 才是项目真正的核心

这是我们和 Akashic 最大的区别。

Akashic 可以是通用 Agent OS。

Run Coach 必须有自己的：

> **Running Intelligence**

所以最重要的 Domain Model 应该先出现。

第一版核心实体：

```text
Runner
Workout
WorkoutFeedback
TrainingGoal
TrainingPlan
PlannedSession
PlanChange
AthleteState
```

关系：

```text
Runner
 │
 ├── Goal
 │
 ├── Workouts
 │
 ├── WorkoutFeedback
 │
 ├── TrainingPlan
 │
 └── AthleteState
```

------

# 5. `Workout` 是客观事实，不是 Memory

例如：

```text
2026-08-27

10.2 km
55:32
avg pace 5:26
avg HR 158
max HR 176
training type = tempo
```

应该直接：

```text
PostgreSQL
```

长期保存。

不能：

```text
embedding
→ memory store
```

否则以后：

> “过去四周平均跑量是多少？”

居然还要依赖向量搜索，那架构就歪了。

所以：

```text
Workout
TrainingPlan
Goal
```

全部属于：

> Canonical Domain Facts

------

# 6. 第二层：Athlete State

这是整个 Run Coach 最值得投入的一层。

它回答的不是：

> 用户说过什么？

而是：

> **这个跑者现在处于什么状态？**

例如：

```text
AthleteState

aerobic_fitness
threshold_fitness
endurance

recent_training_load
fatigue

weekly_volume
weekly_volume_tolerance

workout_completion

pace_hr_trend

recovery

confidence
```

这里不要求第一版就把所有指标做成运动科学论文。

可以逐步演进。

例如第一版：

```text
AthleteState
├── recent_load
├── fatigue
├── workout_completion
├── weekly_volume
├── pace_hr_trend
└── confidence
```

已经够用了。

------

# 7. Athlete State 是 Derived State

它和 Workout 不同。

例如：

```text
Workout
```

是真实发生过的。

而：

```text
fatigue = high
```

是：

> 根据最近训练和反馈推导出来的判断。

所以应该：

```text
Workout / Feedback
        ↓
State Evaluator
        ↓
AthleteStateSnapshot
```

而不是直接覆盖一行：

```text
athlete.fatigue = 0.8
```

我建议保留 Snapshot：

```text
AthleteStateSnapshot

id
user_id

as_of
source_workout_id

training_load
fatigue
fitness
...

confidence

model_version
created_at
```

于是可以看到：

```text
8 月 1 日
State V12

8 月 8 日
State V13

8 月 15 日
State V14
```

以后甚至能问：

> “为什么系统这周把我的长跑降了？”

直接回到当时 State。

------

# 8. 第三层：Memory

这里开始借鉴我们刚才分析的 Mem0 / Letta / Akasha，但不要照搬任何一家。

Run Coach 的 Memory 我建议明确拆成：

```text
Memory
│
├── Working Context
│
├── Semantic Memory
│
└── Episodic Memory
```

注意：

```text
AthleteState
```

不属于 Memory。

它属于 Domain State。

------

# 9. Working Context

这部分类似 Letta 的思想：

> 有些东西根本没必要每轮搜索。

例如：

```text
当前比赛目标
当前训练阶段
当前训练计划
当前 Athlete State 摘要
当前对话任务
```

可以组成：

```text
RunnerWorkingContext
```

例如：

```text
Goal:
2026-10-18 半马 1:50

Training phase:
Threshold development

Current state:
fatigue moderate
recent load rising

Plan:
Week 6 / 10
```

每次 Reasoning 基本都应该有。

所以：

```text
Working Context
```

是 Hot Memory / Hot State。

------

# 10. Semantic Memory

回答：

> **这个用户长期是什么样的人？**

例如：

```text
喜欢晚上跑步

周三晚上通常没空

不喜欢跑步机

容易在连续两天高强度后疲劳

比赛时习惯前半程保守

更喜欢按距离而不是按时间训练
```

但这里也要分：

```text
明确表达
```

和：

```text
模型推断
```

建议数据结构：

```text
SemanticMemory

id
user_id

type
content

confidence
status

valid_from
valid_until

created_at
updated_at
```

再关联：

```text
MemoryEvidence
```

------

# 11. Evidence 是必须保留的

比如：

```text
Memory:

“用户周三晚上通常无法训练”
```

不能凭空存在。

应该能够追到：

```text
Evidence
   │
   └── Turn #382
          │
          └── User Message
              “这学期周三晚上都有课”
```

所以：

```text
SemanticMemory
     │
     └── MemoryEvidence
            │
            ├── turn_id
            ├── message_id
            ├── workout_id
            └── other source
```

这一点非常值得从 Akasha 借。

Akasha 也明确让 Memory Record 能回到原始 message evidence，而不是只保存模型总结。

------

# 12. Semantic Memory 要有 Lifecycle

至少：

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
8 月：

周三晚上有课
status = active
```

后来用户说：

```text
“新学期周三晚上现在有空了。”
```

不要：

```text
DELETE old memory
```

而是：

```text
旧 Memory
status = superseded

新 Memory
status = active
```

于是长期认知是有历史的。

------

# 13. Episodic Memory

这一层回答：

> **以前发生过什么类似的事情？**

例如：

```text
五月训练周期末期出现过一次疲劳积累：

连续两周跑量上涨
→ 间歇训练失败
→ 主观疲劳升高
→ 降负荷一周
→ 随后恢复
```

这就不是一个简单：

```text
用户容易疲劳
```

的 Semantic Fact。

它是完整 Episode。

------

# 14. 第一版 Episodic Memory 不需要 Akasha Graph

Akasha 用：

```text
Turn
→ Hub
→ Membership
→ Temporal Edge
→ Pattern Completion
```

很有意思，但我们完全没必要第一版这么做。

Run Coach 可以先设计：

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

并关联：

```text
EpisodeEvidence
```

例如：

```text
Episode
“第 5 周出现负荷过高并主动降量”

Evidence
├── Workout #201
├── Workout #203
├── Feedback #88
├── AthleteState #51
└── PlanChange #17
```

这个已经非常有价值。

------

# 15. 最关键的一点：Episode 不只来源于聊天

这恰恰是 Run Coach 能比通用 Memory 更强的地方。

Akasha 主要围绕：

```text
Conversation Turn
```

构建 Episode。

而 Run Coach 的 Episode 可以来源：

```text
Conversation
+
Workout
+
AthleteState
+
Plan Change
+
Race
```

所以：

```text
Episode:
“上次高负荷训练周期失配”
```

可能关联：

```text
3 次 Workout
2 条用户反馈
1 次 Athlete State 异常
1 次 Plan Adaptation
```

这比单纯 Chat Memory 更符合垂直 Agent。

------

# 16. 第四层：Agent Runtime

Agent Runtime 本身不要拥有业务逻辑。

它应该只负责：

```text
理解当前目标
构建 Context
Reason
调用 Tool
接收 Observation
继续 Reason
生成 Response / Action
```

结构：

```text
User Input
    ↓
Turn Runtime
    ↓
Context Assembler
    ↓
Reasoner
    ↓
Tool Runtime
    ↓
Observation
    ↓
Reasoner
    ↓
Response / Domain Action
```

------

# 17. Context Assembler 非常重要

真正发给模型的 Context 不应该：

```text
SELECT everything
```

而是：

```text
ContextBundle
│
├── System Instructions
├── Working Context
├── Recent Conversation
├── Retrieved Semantic Memory
├── Retrieved Episodes
├── Tool Schemas
└── Current User Input
```

也就是：

```text
                  Context Assembler

                         │
        ┌────────────────┼───────────────────┐
        │                │                   │
        ▼                ▼                   ▼
Domain Context      Memory Retrieval    Conversation
        │                │                   │
        └────────────────┼───────────────────┘
                         ▼
                       LLM
```

这是未来 Agent 智能程度非常重要的一层。

------

# 18. Memory Retrieval 也应该分开

例如用户说：

> 最近怎么越来越跑不动了？

可以分别查：

```text
Semantic Retrieval

“这个用户有哪些相关长期特点？”
```

可能得到：

```text
以前连续高负荷时恢复较慢
```

而：

```text
Episodic Retrieval

“以前有没有类似情况？”
```

得到：

```text
五月有一次类似训练失配 Episode
```

同时 Domain Tools：

```text
get_recent_workouts
get_athlete_state
get_current_plan
```

提供当前事实。

最终：

```text
Current Facts
+
Long-term Facts
+
Historical Experience
```

一起进入 Agent。

这才是真正像长期教练。

------

# 19. 第五层：Tool Runtime

这一层可以比较直接借 Akashic 的思想。

我建议最终模块：

```text
Tool Runtime
│
├── Tool
├── ToolRegistry
├── ToolCatalog
├── ToolSearch
├── ToolResolver
└── ToolExecutor
```

------

# 20. Tool 分成领域能力，而不是 CRUD

第一批真正有意义的 Tool：

```text
Training Data
├── get_recent_workouts
├── get_workout_detail
└── analyze_workout

Runner State
├── get_athlete_state
├── analyze_training_load
└── analyze_training_trend

Plan
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

模型应该调用：

```text
analyze_training_load
```

而不是：

```text
select * from workouts
```

Tool 是：

> Domain Capability。

------

# 21. Tool Runtime 内部职责

Akashic 把 `Registry`、Search、Discovery State、Executor 分开，这是很值得学的。Registry 保存 executable、metadata 和搜索 document；Executor 独立处理授权、参数准备、执行和结果观察。

我们的设计可以是：

```text
ToolRegistry
    ↓
有哪些能力


ToolCatalog / Search
    ↓
当前任务可能需要哪些


ToolResolver
    ↓
给模型哪些 Schema


ToolExecutor
    ↓
真正执行
```

Tool metadata：

```text
name
description

tags

risk

source

input_schema
output_schema
```

------

# 22. ToolExecutionContext 要独立于模型参数

这个 Akashic 设计我认为可以直接借思想。

模型：

```json
{
  "days": 14
}
```

Runtime：

```text
user_id
run_id
turn_id
request_id
timestamp
```

最终：

```text
LLM Arguments
       +
Trusted Execution Context
       ↓
Tool
```

而不是允许模型：

```json
{
  "user_id": "abc",
  "days": 14
}
```

Akashic 当前也是通过不可变 `ToolExecutionContext` + `ContextVar` 保存 runtime provenance。

------

# 23. Memory 的写入不要发生在 Reasoning 中途

这也是我很建议继承 Akasha 的一点。

Akasha 把：

```text
Retrieve
```

和：

```text
Learn
```

严格分开，只有 committed turn 才进入长期投影。

Run Coach 可以采用：

```text
User Input
    ↓
Agent Run
    ↓
Response
    ↓
Turn Committed
    ↓
Post-Commit Events
    │
    ├── Semantic Memory Projector
    ├── Episode Projector
    └── Eval Collector
```

这样：

```text
Agent Reasoning
```

不会一边思考一边随意污染长期 Memory。

------

# 24. Domain State 更新也建议 Event Driven

例如：

```text
WorkoutImported
       ↓
AthleteStateProjector
       ↓
New AthleteStateSnapshot
```

或者：

```text
WorkoutFeedbackSubmitted
       ↓
AthleteStateProjector
```

然后：

```text
AthleteStateChanged
       ↓
Agent / Plan Adaptation
```

所以我们最终会有一些很有价值的 Domain Event：

```text
WorkoutImported
WorkoutAnalyzed

FeedbackSubmitted

AthleteStateUpdated

PlanCreated
PlanAdapted

TurnCommitted
```

注意这里不是为了搞 Event Sourcing。

只是用 Event：

> 解耦各个 Projection。

------

# 25. Memory Projector 和 Athlete State Projector 必须分开

非常重要。

```text
TurnCommitted
   │
   └── Memory Projector
```

解决：

> 这次交互有没有形成值得长期记住的用户信息？

而：

```text
WorkoutCompleted
   │
   └── AthleteState Projector
```

解决：

> 这次训练对当前能力和疲劳意味着什么？

不要做成：

```text
MemoryUpdater
```

什么都管。

------

# 26. 一条未来的真实场景

用户说：

> 昨天那个间歇跑崩了，最后两组完全跑不动，今天腿也挺酸，这周后面怎么练？

完整路径应该是：

```text
User
 ↓
Agent Runtime
 ↓
Context Assembler
 │
 ├── Working Context
 │      goal
 │      current block
 │      athlete state
 │
 ├── Semantic Memory
 │      long-term preferences
 │
 └── Episodic Memory
        similar past cases
 ↓
Reasoner
 ↓
get_workout_detail(yesterday)
 ↓
Observation
 ↓
get_recent_workouts()
 ↓
Observation
 ↓
analyze_training_load()
 ↓
Observation
 ↓
get_active_plan()
 ↓
Observation
 ↓
Reasoner
 ↓
判断：
近期负荷上涨
训练完成度下降
主观疲劳增加
 ↓
adapt_training_plan()
 ↓
PlanChange
 ↓
Response
```

之后：

```text
TurnCommitted
      │
      └── Memory Projector

PlanAdapted
      │
      └── Episode Projector

Workout / Feedback
      │
      └── AthleteState Projector
```

这就形成长期闭环。

------

# 27. 数据库我初步会划四个 Schema

先不设计具体列，边界可以先定：

```text
PostgreSQL

identity.*
├── users
└── auth...

coaching.*
├── workouts
├── workout_feedback
├── goals
├── training_plans
├── planned_sessions
├── plan_changes
└── athlete_state_snapshots


agent.*
├── threads
├── turns
├── agent_runs
├── tool_calls
└── events


memory.*
├── semantic_memories
├── memory_evidence
├── episodes
└── episode_evidence
```

这是**逻辑 schema**，并不意味着必须真建四个 PostgreSQL Schema；但模块边界最好保持这个概念。

------

# 28. Redis 现阶段只做短生命周期状态

不要把 Redis 又变成万能数据库。

我建议只放：

```text
SSE run state

rate limit

短期 cache

distributed lock（真正需要时）

task progress
```

长期 Memory 不应该放 Redis。

Athlete State 也以 PostgreSQL Snapshot 为准。

------

# 29. 异步 Worker 最自然的任务

例如：

```text
memory_projection

episode_projection

athlete_state_recompute

workout_deep_analysis

embedding_generation

eval_batch
```

这些都是：

> HTTP 没必要等。

至于 Celery + RabbitMQ 还是其他实现，是第二层技术选型问题，不影响现在 Architecture Contract。

------

# 30. 第一版目录我会这样设计

```text
backend/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   ├── dependencies/
│   │   └── schemas/
│   │
│   ├── identity/
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   │
│   ├── coaching/
│   │   ├── domain/
│   │   │   ├── workout/
│   │   │   ├── athlete/
│   │   │   ├── plan/
│   │   │   └── goal/
│   │   │
│   │   ├── application/
│   │   └── infrastructure/
│   │
│   ├── agent/
│   │   ├── runtime/
│   │   ├── reasoning/
│   │   ├── context/
│   │   ├── turns/
│   │   └── events/
│   │
│   ├── memory/
│   │   ├── semantic/
│   │   ├── episodic/
│   │   ├── retrieval/
│   │   ├── projection/
│   │   └── models/
│   │
│   ├── tools/
│   │   ├── registry/
│   │   ├── search/
│   │   ├── executor/
│   │   └── builtin/
│   │
│   ├── workers/
│   │
│   ├── evals/
│   │
│   └── infrastructure/
│       ├── database/
│       ├── cache/
│       ├── queue/
│       ├── llm/
│       └── observability/
│
├── tests/
└── docs/
```

这个目录我暂时认为比较适合。

但**现在先别创建 50 个空文件**。

目录只是表达边界。

------

# 31. 我会把整个架构浓缩成这一张图

```text
                         ┌──────────────┐
                         │    Runner    │
                         └──────┬───────┘
                                │
                          Text / Data
                                │
                                ▼
                       ┌────────────────┐
                       │ Agent Runtime  │
                       └───────┬────────┘
                               │
                     Context Assembler
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
 Working Context         Memory Retrieval        Conversation
        │                      │
        │              ┌───────┴────────┐
        │              ▼                ▼
        │          Semantic          Episodic
        │           Memory            Memory
        │
        ▼
 Coaching Domain
        │
        ├── Workout
        ├── Goal
        ├── Training Plan
        └── Athlete State
                               │
                               ▼
                           Reasoner
                               │
                               ▼
                         Tool Runtime
                               │
               ┌───────────────┼──────────────┐
               ▼               ▼              ▼
          Training Tool    State Tool      Plan Tool
               │               │              │
               └───────────────┼──────────────┘
                               ▼
                         Domain Services
                               │
                               ▼
                           PostgreSQL
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
        Domain Events                  TurnCommitted
                │                             │
                ▼                             ▼
     AthleteState Projector           Memory Projectors
                                              │
                                     ┌────────┴────────┐
                                     ▼                 ▼
                                  Semantic          Episode
```

------

# 32. 第一阶段我们真正要实现的东西其实很少

架构虽然完整，但 Phase 1 不应该一口吃完。

第一阶段只落：

```text
1. Domain Model
2. Conversation / Turn
3. Minimal Agent Runtime
4. Context Assembler
5. 简单 Tool 接口
6. PostgreSQL
```

Memory 先只留接口：

```python
MemoryRetriever
MemoryProjector
```

Tool 也先只留：

```python
Tool
ToolExecutor
```

先证明：

```text
用户
→ Agent
→ 查真实训练数据
→ Reason
→ 回答
```

这一条 Vertical Slice 能漂亮跑通。

然后下一阶段再把它升级成：

```text
Tool Registry / Search
```

再下一阶段：

```text
Semantic / Episodic Memory
```

最后：

```text
Eval
```

这就和之前确定的重构节奏完全吻合，但这次底层架构已经从“旧 Harness”思维切换成了新的认知模型。
