# Phase 3 — Coaching Intelligence

> **Status:** Active
> **Depends on:** `docs/ARCHITECTURE.md`
> **Previous:** `docs/phases/PHASE_2_DYNAMIC_TOOL_RUNTIME.md`
> **Scope:** Training Analysis + Athlete State Evaluation + Analysis Tools + Constrained Plan Adaptation

---

# 1. Phase Goal

Phase 1 已建立：

```text
Identity
Conversation
Agent Runtime
Context
Execution Trace
Lifecycle
```

Phase 2 已建立：

```text
Dynamic Tool Runtime
Native Tool Calling
Tool Discovery
Registry / Resolver / Executor
Trusted ToolExecutionContext
```

但当前系统仍缺少 Run Coach 最核心的一层：

> **Running Intelligence。**

目前 Agent 可以读取 Workout、WorkoutFeedback、Goal、Plan 与 AthleteStateSnapshot，但 AthleteStateSnapshot 仍主要由 seed / fixture 提供，系统没有正式状态算法；Training Analysis 也不存在；计划只能读取，不能安全地产生版本化调整。

因此 Phase 3 要完成：

```text
Canonical Training Facts
        ↓
Training Analysis
        ↓
Athlete State Evaluator
        ↓
Versioned AthleteStateSnapshot
        ↓
Agent Evidence Investigation
        ↓
PlanChange Proposal
        ↓
TurnCommitted
        ↓
Pending User Confirmation
        ↓
Freshness + Domain Validation
        ↓
TrainingPlan Version N + 1
```

Phase 3 完成后，Run Coach 应第一次从：

```text
“可以读取跑步数据的 Agent”
```

变成：

> **能够根据真实训练证据理解跑者当前状态，并安全提出后续训练调整的长期教练系统。**

---

# 2. Non-Goals

Phase 3 不实现：

```text
Semantic Memory
Episodic Memory
Memory Projection

Workout 外部平台导入
Garmin / Strava
截图解析

Worker / Celery / RabbitMQ
Transactional Outbox

MCP
Multi-Agent
Embedding Tool Search

VO2max 推算
乳酸阈值模型
CTL / ATL / TSB
ACWR 风险区间

伤病概率
医疗诊断

通用训练计划编辑器
自由修改 prescription

自动无确认激活训练计划
```

Phase 3 的目标不是建立一套完整运动科学平台，而是：

> **建立正确、保守、可解释、可版本化的第一版 Coaching Intelligence。**

---

# 3. Architectural Invariants

Phase 3 必须继续遵守以下边界：

```text
Workout / WorkoutFeedback / Plan
=
Canonical Facts

Training Analysis
=
Derived Metrics

AthleteStateSnapshot
=
Derived Domain State

PlanChange
=
Proposed Domain Mutation

Agent Runtime
=
Investigation / Decision Runtime

Tool Runtime
=
Capability Execution Infrastructure
```

禁止：

```text
LLM
↓
直接决定 fatigue_level
↓
写 AthleteStateSnapshot
```

禁止：

```text
Prompt
↓
偷偷实现训练负荷算法
```

禁止：

```text
ToolExecutor
↓
实现训练业务规则
```

禁止：

```text
Agent Tool Call
↓
直接激活 TrainingPlan
```

Running Intelligence 必须主要位于：

```text
coaching/domain
coaching/application
```

Agent 与 Tool 只是调用它。

---

# 4. Final Phase 3 Flow

完整运行关系：

```text
Workout / Feedback
        ↓
TrainingAnalysisService
        ↓
AthleteStateEvaluatorV1
        ↓
AthleteStateRecomputeService
        ↓
AthleteStateSnapshot Vn
        ↓

──────────────────────────────

User
 ↓
ChatService
 ↓
AgentRuntime
 ↓
Tool Runtime
 ↓
get_recent_workouts
analyze_training_load
analyze_workout
get_latest_athlete_state
get_active_plan
 ↓
propose_plan_adaptation
 ↓
PlanChange = draft
 ↓
Agent FinalAction
 ↓
Transaction B
 ↓
TurnCommitted
 ↓
PlanChange = pending_confirmation

──────────────────────────────

User explicitly confirms
 ↓
HTTP Confirmation API
 ↓
Authentication / RequestContext
 ↓
PlanAdaptationService.confirm()
 ↓
Freshness Check
 ↓
Domain Validation
 ↓
Atomic Plan Activation
 ↓
Plan Vn     → SUPERSEDED
Plan Vn+1   → ACTIVE
PlanChange  → CONFIRMED
```

---

# 5. Training Evidence Window

Phase 3 所有状态计算都必须具有明确：

```text
as_of
```

`as_of` 来自可信系统时间：

```text
Clock
RequestContext.timestamp
```

不能来自：

```text
LLM arguments
HTTP request body arbitrary timestamp
Prompt
```

任何状态计算查询必须同时具有：

```text
start <= evidence_time <= as_of
```

不能只有下界。

例如：

```text
list_between(
    user_id,
    start,
    end=as_of
)
```

避免：

```text
用未来 Workout
计算过去 AthleteStateSnapshot
```

---

# 6. Repository Evidence Queries

扩展 WorkoutRepository：

```text
list_between(
    user_id,
    start,
    end,
    limit
)
```

以及批量 Feedback 查询：

```text
list_feedback_for_workouts(
    user_id,
    workout_ids
)
```

禁止 TrainingAnalysisService 对每个 Workout：

```text
for workout:
    await get_feedback(workout.id)
```

形成 N+1 查询。

所有查询继续强制：

```text
user_id
```

隔离。

---

# 7. Training Analysis Domain

新增：

```text
backend/app/coaching/domain/analysis/
    models.py
    training_load.py
```

Training Analysis：

> 根据已有事实进行可重复计算。

它不：

```text
修改 Workout
写 Athlete State
修改 Plan
调用 LLM
```

---

# 8. Session-RPE Load

Phase 3 v1 的内部训练负荷指标：

```text
session_rpe_load
=
duration_minutes × perceived_exertion
```

只有同时存在：

```text
Workout.duration_s
+
WorkoutFeedback.perceived_exertion
```

才能计算。

禁止：

```text
缺 RPE
↓
根据 workout_type 猜一个 RPE
```

禁止：

```text
interval = 1.65
tempo = 1.5
```

这类人为 type factor 被包装成生理负荷。

Workout Type 只用于：

```text
training category
quality-session signal
```

不作为 session-RPE 的替代值。

---

# 9. Training Load Window

`analyze_training_load` 默认计算：

```text
Current Window
=
as_of 往前 7 天

Previous Window
=
Current Window 之前的 7 天
```

每个窗口输出：

```text
workout_count

total_duration_s
total_distance_m

quality_session_count

srpe_load_sum

srpe_eligible_count
srpe_available_count
srpe_coverage
```

其中：

```text
srpe_coverage
=
有 duration + RPE 的 workout 数
/
有 duration 的 workout 数
```

没有 eligible workout：

```text
coverage = None
```

---

# 10. Partial Load Semantics

Training Analysis 可以返回：

```text
partial_srpe_load
```

但必须同时返回：

```text
coverage
is_partial
```

不能把不完整的 sRPE Sum 冒充完整训练负荷。

AthleteStateSnapshot 中：

```text
recent_training_load
```

仅当：

```text
srpe_coverage >= 0.5
```

时写入 7 日 sRPE Sum。

否则：

```text
recent_training_load = None
```

并产生：

```text
low_training_load_coverage
```

Signal。

`0.5` 是 Phase 3 v1 的工程 Evidence Coverage 门槛，不解释为运动科学阈值。

---

# 11. Training Load Comparison

只有：

```text
current coverage >= 0.5
previous coverage >= 0.5
previous load > 0
```

时才输出：

```text
load_change_ratio
```

否则：

```text
load_change_ratio = None
```

并返回原因：

```text
insufficient_current_coverage
insufficient_previous_coverage
no_previous_baseline
```

禁止将这个 Ratio 表述为：

```text
injury risk
overtraining probability
safe zone
```

它只是：

> 描述性的训练趋势。

---

# 12. Workout Analysis

新增：

```text
WorkoutAnalysisService
```

输入：

```text
user_id
workout_id
as_of
```

输出：

```text
Workout facts

Feedback

session-RPE load

quality_session

same_day_planned_sessions

heart-rate facts
```

`same_day_planned_sessions` 只是：

> 同日计划上下文。

不能因此推导：

```text
Workout 完成了 PlannedSession
```

Phase 3 不解析 Feedback.note 得出：

```text
reported_slowdown
```

等新的结构化事实。

原始 note 可以作为 Evidence 返回给 Agent，由 Agent在回答中解释，但 Domain Analysis 不进行自然语言事实创造。

---

# 13. Athlete State Model

继续使用：

```text
AthleteStateSnapshot
```

现有核心字段：

```text
id
user_id

version
as_of

fatigue_level
recovery_level

recent_training_load
workout_completion_rate

confidence

algorithm_version
created_at
```

Phase 3 增加：

```text
training_load_coverage
signals
```

其中：

```text
training_load_coverage: float | None
```

`signals` 为 JSONB 持久化的结构化状态依据。

---

# 14. AthleteStateSignal

Domain 定义：

```text
AthleteStateSignal

code
severity
message
evidence_refs
```

`evidence_refs` 可以引用：

```text
Workout ID
WorkoutFeedback ID
Training Analysis Window
```

Signal 示例：

```text
high_subjective_fatigue
high_soreness
recent_quality_session
moderate_subjective_fatigue
low_training_load_coverage
recent_load_increase
insufficient_recent_feedback
```

Signal 的作用是：

> 让 Athlete State 可解释。

---

# 15. AthleteStateEvaluatorV1

新增：

```text
backend/app/coaching/domain/athlete/evaluator.py
```

正式类：

```text
AthleteStateEvaluatorV1
```

算法版本：

```text
phase3.v1
```

Evaluator 必须是纯领域逻辑。

不得依赖：

```text
SQLAlchemy
Repository
FastAPI
Tool
LLM
Redis
系统墙钟
```

输入：

```text
AthleteStateEvidence
```

输出：

```text
AthleteStateAssessment
```

Application Service 再负责形成 Snapshot。

---

# 16. AthleteStateEvidence

至少包含：

```text
as_of

recent_workouts
recent_feedback

training_load_analysis
```

Phase 3 不把 Plan Completion 强行塞入 Evidence。

---

# 17. Fatigue v1

Fatigue 必须优先使用用户明确报告的状态信息。

## HIGH

最近 72 小时存在 Feedback，并满足任一：

```text
subjective_fatigue >= 8
```

或：

```text
soreness >= 8
```

或：

```text
subjective_fatigue >= 7
AND
soreness >= 6
```

或：

```text
subjective_fatigue >= 7
AND
关联 Workout 是 tempo / interval / race
```

则：

```text
fatigue_level = HIGH
```

---

## MODERATE

最近 72 小时存在：

```text
subjective_fatigue >= 6
```

或：

```text
soreness >= 6
```

则：

```text
fatigue_level = MODERATE
```

高 RPE：

```text
perceived_exertion >= 8
```

只能产生：

```text
hard_session
```

Signal。

不能单独推导：

```text
fatigue = HIGH
```

---

## LOW

只有最近 72 小时存在明确 Feedback：

```text
subjective_fatigue <= 4
AND
soreness <= 4
```

才能：

```text
fatigue_level = LOW
```

---

## UNKNOWN

如果没有足够的直接疲劳 Evidence：

```text
fatigue_level = None
```

系统必须允许：

> 不知道。

训练负荷变化只能增加 Signal，不能单独把 LOW / UNKNOWN 推成 HIGH。

---

# 18. Recovery v1

## POOR

最近 72 小时：

```text
subjective_fatigue >= 8
OR
soreness >= 8
```

则：

```text
recovery_level = POOR
```

---

## FAIR

最近 72 小时：

```text
subjective_fatigue >= 6
OR
soreness >= 6
```

则：

```text
recovery_level = FAIR
```

---

## GOOD

最近 72 小时存在明确 Feedback：

```text
subjective_fatigue <= 4
AND
soreness <= 4
```

且：

```text
最近 24 小时没有 quality session
```

则：

```text
recovery_level = GOOD
```

---

## UNKNOWN

其他情况：

```text
recovery_level = None
```

禁止：

```text
昨天跑了 Interval
=
今天 recovery = POOR
```

Quality Session 只能作为辅助 Signal。

---

# 19. Confidence v1

Confidence 表示：

> 当前判断拥有多少可靠 Evidence。

不是：

```text
伤病概率
模型正确率
```

固定公式：

```text
confidence = 0.20
```

最近 72 小时存在 Feedback：

```text
+ 0.40
```

最近 14 天至少 3 次 Workout：

```text
+ 0.20
```

Training Load Coverage >= 0.5：

```text
+ 0.20
```

最终：

```text
clamp(0.20, 1.00)
```

算法变化必须升级：

```text
algorithm_version
```

---

# 20. Workout Completion Rate

Phase 3：

```text
workout_completion_rate = None
```

原因：

当前系统没有正式：

```text
PlannedSession
↔
Workout
```

执行关联。

禁止采用：

```text
scheduled_date 当天存在 Workout
=
完成 PlannedSession
```

这种近似。

正式：

```text
PlannedSessionExecution
```

属于后续阶段。

Phase 3 不为了填满 Snapshot 字段而制造不可靠 Derived State。

---

# 21. AthleteStateRecomputeService

Application Layer 增加：

```text
AthleteStateRecomputeService
```

职责：

```text
load evidence bounded by as_of
        ↓
Training Analysis
        ↓
AthleteStateEvaluatorV1
        ↓
append AthleteStateSnapshot
```

它是未来：

```text
WorkoutImported
WorkoutFeedbackSubmitted
        ↓
Athlete State Projector
        ↓
AthleteStateRecomputeService
```

的正式入口。

Phase 3 不实现 Worker / Projector。

---

# 22. Recompute Is Not an Agent Tool

禁止注册：

```text
recompute_athlete_state
```

为 Agent Tool。

Athlete State 的生命周期属于系统，而不是模型决策。

Phase 3 中：

```text
测试
seed / fixture alignment
内部 application command
```

可以显式调用：

```text
AthleteStateRecomputeService.recompute()
```

未来事件驱动也调用同一个 Service。

---

# 23. Snapshot Append Semantics

AthleteStateSnapshot：

```text
append-only
```

禁止：

```text
UPDATE old snapshot
```

规则：

### No Snapshot

```text
version = 1
```

### as_of < latest.as_of

```text
fail
```

禁止历史回退。

### as_of == latest.as_of

若：

```text
algorithm_version 相同
+
所有 assessment 字段相同
```

则：

```text
返回已有 Snapshot
```

不创建空版本。

如果算法版本或 Assessment 改变：

```text
append version + 1
```

### as_of > latest.as_of

```text
append version + 1
```

---

# 24. Snapshot Concurrency

数据库已有：

```text
UNIQUE(user_id, version)
```

但 Phase 3 不允许简单：

```text
SELECT max(version)
↓
version + 1
↓
INSERT
```

无并发保护。

`append_snapshot()` 必须：

```text
BEGIN

SELECT users
WHERE id = user_id
FOR UPDATE

read latest snapshot

validate as_of

allocate next version

INSERT snapshot

COMMIT
```

使用：

```text
UserRow FOR UPDATE
```

作为用户维度 Domain Mutation 锁。

Plan Activation 使用同一把用户锁。

---

# 25. Analysis Tools

Phase 3 新增两个 Tool：

```text
analyze_training_load
analyze_workout
```

均：

```text
always_on = false
```

必须通过：

```text
search_tools
```

发现。

---

# 26. Tool Risk Evolution

当前 ToolRisk 扩展为：

```text
READ_ONLY
ANALYZE
DRAFT
MUTATING
```

现有查询 Tool：

```text
READ_ONLY
```

Phase 3：

```text
analyze_training_load → ANALYZE
analyze_workout       → ANALYZE
propose_plan_adaptation → DRAFT
```

模型 Runtime 允许执行：

```text
READ_ONLY
ANALYZE
DRAFT
```

默认拒绝：

```text
MUTATING
```

不能简单把 Executor 改成：

```text
任何声明 risk=mutating
都允许模型执行
```

---

# 27. Plan Adaptation Scope

Phase 3 只支持一个：

```text
change_type = reduce_upcoming_load
```

不实现通用 Plan Editor。

Proposal 输入：

```text
based_on_plan_version

based_on_state_version

horizon_days

reason
```

其中：

```text
1 <= horizon_days <= 7
```

模型不能提供：

```text
user_id
as_of
target session diff
new prescription
new plan version
```

真正：

```text
user_id
turn_id
run_id
as_of
```

来自 ToolExecutionContext。

---

# 28. Preconditions for reduce_upcoming_load

Phase 3 v1 只在：

```text
fatigue_level = HIGH
OR
recovery_level = POOR
```

时允许生成降负荷 Proposal。

否则返回 Domain Error：

```text
state_does_not_require_v1_reduction
```

这不是说其他状态永远不需要调整。

只是：

> Phase 3.v1 有意只实现保守、证据最明确的一类调整。

---

# 29. Adaptation Window

作用窗口：

```text
[as_of.date + 1,
 as_of.date + horizon_days]
```

禁止修改：

```text
过去 Session

当天已经开始的 Session

horizon 外 Session

Plan 日期范围外内容
```

---

# 30. V1 Session Mutation

Phase 3 唯一自动支持：

```text
TEMPO
INTERVAL
        ↓
REST
```

新的 PlannedSession：

```text
session_type = REST

title = "恢复休息（调整自：<old title>）"

prescription = {}
```

原因：

当前 prescription 是自由 JSON。

Phase 3 不具备：

```text
用户 Easy Pace 模型
结构化强度处方系统
```

所以：

```text
Tempo → Easy
```

同时保留原 pace prescription 会产生语义冲突。

v1 选择：

> 保守且确定性的 REST replacement。

---

# 31. Sessions Not Modified

Phase 3 不自动修改：

```text
EASY
LONG_RUN
OTHER
REST
```

Phase 3 也绝不自动修改：

```text
RACE
```

如果 Window 中存在 Race：

```text
Proposal Observation
```

应明确包含：

```text
race_session_not_modified
```

Race 与 Goal 强绑定，必须由未来更高级的 Coaching 决策处理。

---

# 32. Empty Adaptation

如果目标窗口不存在：

```text
TEMPO
INTERVAL
```

则：

```text
propose_plan_adaptation
```

返回 Domain Error：

```text
no_applicable_sessions
```

禁止生成空 PlanChange。

---

# 33. PlanStatus

扩展：

```text
ACTIVE
SUPERSEDED
COMPLETED
CANCELLED
```

语义：

```text
COMPLETED
=
计划正常执行结束

SUPERSEDED
=
因为新 Plan Version 激活而退出 Active
```

新版本激活后：

```text
Plan Vn
ACTIVE → SUPERSEDED

Plan Vn+1
→ ACTIVE
```

---

# 34. Plan Version Constraint

新增数据库约束：

```text
UNIQUE(user_id, version)
```

继续保留：

```text
每个 user 最多一个 ACTIVE plan
```

---

# 35. PlanChange

新增 Domain Model：

```text
PlanChange

id
user_id

from_plan_id
from_plan_version

based_on_state_id
based_on_state_version

source_turn_id
source_run_id

as_of

change_type
payload
reason

status

created_at
resolved_at

resulting_plan_id
```

---

# 36. PlanChangeStatus

Phase 3 正式状态：

```text
DRAFT

PENDING_CONFIRMATION

CONFIRMED

REJECTED

STALE

ABANDONED
```

不引入没有实际行为的状态。

---

# 37. PlanChange Payload

Payload 必须是结构化 Diff：

```text
horizon_days

changes: [
    {
        source_session_id,
        scheduled_date,

        from_type,
        to_type,

        old_title,
        new_title,

        old_prescription,
        new_prescription
    }
]
```

Payload 由 Domain Service 生成。

模型不能自己提供：

```text
changes
```

避免模型绕过 Domain Adaptation Rule。

---

# 38. PlanChange Proposal

`propose_plan_adaptation`：

```text
risk = DRAFT
```

执行：

```text
load Active Plan
↓
load Latest Athlete State
↓
verify based_on versions
↓
Domain Adaptation
↓
create PlanChange(DRAFT)
```

它绝不：

```text
deactivate Active Plan
create new Active Plan
```

---

# 39. Unresolved Proposal Rule

一个用户同时只允许一个：

```text
DRAFT
or
PENDING_CONFIRMATION
```

PlanChange。

数据库使用部分唯一约束保护。

如果已经存在 Pending Proposal：

```text
new propose
→ conflict
```

用户必须：

```text
confirm
reject
```

或旧 Proposal 因 Freshness 失效成为：

```text
STALE
```

之后才能重新生成。

Phase 3 不做隐式“新 Proposal 自动覆盖旧 Proposal”。

---

# 40. Turn Lifecycle Integration

PlanChange Proposal 在 AgentRun 内产生时：

```text
status = DRAFT
```

DRAFT 不能被确认。

---

## TurnCommitted

收到：

```text
TurnCommitted
```

后：

```text
本 Turn 的 DRAFT
→
PENDING_CONFIRMATION
```

---

## TurnFailed

```text
DRAFT
→
ABANDONED
```

---

## TurnCancelled

```text
DRAFT
→
ABANDONED
```

---

# 41. Lifecycle Adapter

不要让 `agent` 模块直接依赖 PlanChange。

增加 Adapter，例如：

```text
infrastructure/
└── lifecycle/
    └── plan_change_listener.py
```

它订阅：

```text
TurnCommitted
TurnFailed
TurnCancelled
```

然后调用：

```text
PlanAdaptationService
```

Agent Lifecycle Event 本身不包含 Coaching 逻辑。

Phase 3 接受现有 in-process post-commit delivery 的可靠性限制。

不在本阶段引入 Outbox。

---

# 42. Confirmation Is Not an Agent Tool

Phase 3 **禁止**：

```text
confirm_plan_adaptation
```

注册为 Tool。

否则：

```text
LLM 判断用户同意
↓
LLM 调 confirm Tool
↓
真正修改计划
```

会让 User Confirmation 退化为 Model Decision。

真正确认必须通过可信 Application Boundary。

---

# 43. Confirmation API

新增：

```text
GET
/api/v1/plan-changes/{plan_change_id}
```

```text
POST
/api/v1/plan-changes/{plan_change_id}/confirm
```

```text
POST
/api/v1/plan-changes/{plan_change_id}/reject
```

user_id：

```text
JWT
↓
RequestContext
```

禁止请求 Body 指定。

所有查询：

```text
user_id + plan_change_id
```

双重过滤。

跨用户访问返回：

```text
404
```

避免泄漏对象存在性。

---

# 44. Confirmation Preconditions

只有：

```text
status = PENDING_CONFIRMATION
```

可以确认。

确认时重新读取：

```text
Current Active Plan
Latest Athlete State
```

并检查：

```text
Current Plan ID
==
from_plan_id
```

```text
Current Plan Version
==
from_plan_version
```

```text
Latest State ID
==
based_on_state_id
```

```text
Latest State Version
==
based_on_state_version
```

任一不一致：

```text
PlanChange → STALE
```

返回：

```text
409 Conflict
```

绝不继续激活。

---

# 45. Domain Validation Before Activation

必须再次验证：

```text
PlanChange 属于当前 user

Base Plan 仍 Active

Base Plan Version 正确

Athlete State 正确

change_type = reduce_upcoming_load

每个 source_session
属于 Base Plan

日期在 adaptation window 内

只存在
TEMPO/INTERVAL → REST

RACE 没有变化

new prescription = {}

Plan 时间范围不变

goal_id 不变
```

禁止信任数据库里的 JSON Payload 因为“它之前验证过”。

Activation 前再次验证。

---

# 46. Atomic Plan Activation

Plan 激活不能通过多个各自提交的 Repository 方法拼接。

新增 Persistence Port：

```text
PlanActivationStore
```

职责：

> 在一个数据库事务内执行经过 Domain Validation 的版本激活。

流程：

```text
BEGIN

lock UserRow FOR UPDATE

reload PlanChange

reload current Active Plan

reload Latest Athlete State

freshness compare

insert Plan Version N + 1

copy all PlannedSession
    ↓
apply validated changes

old Plan
ACTIVE → SUPERSEDED

new Plan
→ ACTIVE

PlanChange
→ CONFIRMED
resulting_plan_id = new plan id

COMMIT
```

不能：

```text
先把 old Plan 失活
COMMIT
再创建 new Plan
```

---

# 47. Why UserRow Lock

Athlete State Recompute 与 Plan Activation 都必须：

```text
SELECT UserRow
FOR UPDATE
```

因此同一用户的：

```text
Athlete State append
Plan Activation
```

不会并发越过 Freshness Check。

避免：

```text
Confirm 读取 State V8
          │
          ├── 并发产生 State V9
          │
          └── 仍然基于 V8 激活 Plan
```

两个 Mutation 共享用户级锁后：

```text
要么 V9 先完成
→ Confirmation stale

要么 Confirmation 先完成
→ V9 后产生
```

状态清晰。

---

# 48. Confirmation Idempotency

相同：

```text
plan_change_id
```

被重复 confirm：

如果已经：

```text
CONFIRMED
```

则返回原：

```text
resulting_plan_id
```

不能创建：

```text
Plan Version N + 2
```

因此 PlanChange ID 本身就是该 Mutation 的主要幂等键。

---

# 49. Reject

只有：

```text
PENDING_CONFIRMATION
```

可以：

```text
REJECTED
```

重复 reject：

返回当前 rejected 状态。

Confirmed / Stale / Abandoned：

不能 reject。

---

# 50. Persistence Changes

新增 Migration：

```text
0003_phase3_coaching_intelligence.py
```

至少包含：

### athlete_state_snapshots

新增：

```text
training_load_coverage FLOAT NULL

signals JSONB NOT NULL DEFAULT []
```

---

### training_plans

新增：

```text
UNIQUE(user_id, version)
```

Status 支持：

```text
superseded
```

---

### plan_changes

新增表：

```text
id UUID PK

user_id FK

from_plan_id FK
from_plan_version INT

based_on_state_id FK
based_on_state_version INT

source_turn_id UUID
source_run_id UUID

as_of TIMESTAMPTZ

change_type VARCHAR

payload JSONB
reason TEXT

status VARCHAR

created_at TIMESTAMPTZ
resolved_at TIMESTAMPTZ NULL

resulting_plan_id FK NULL
```

并建立：

```text
user_id
status
created_at
```

必要索引。

建立部分唯一约束：

```text
同一 user
最多一个
DRAFT / PENDING_CONFIRMATION
```

---

# 51. Domain / Application Files

建议新增：

```text
backend/app/coaching/domain/analysis/
├── __init__.py
├── models.py
└── training_load.py
```

```text
backend/app/coaching/domain/athlete/
├── models.py
├── signals.py
└── evaluator.py
```

```text
backend/app/coaching/domain/plan/
├── models.py
├── adaptation.py
└── validator.py
```

Application：

```text
backend/app/coaching/application/
├── training_analysis_service.py
├── athlete_service.py
└── plan_adaptation_service.py
```

Ports：

```text
backend/app/coaching/ports/
├── workout_repository.py
├── athlete_state_repository.py
├── plan_repository.py
├── plan_change_repository.py
└── plan_activation_store.py
```

---

# 52. Tool Files

新增：

```text
backend/app/tools/builtin/training_analysis.py
```

包含：

```text
AnalyzeTrainingLoadTool
AnalyzeWorkoutTool
```

新增：

```text
backend/app/tools/builtin/plan_adaptation.py
```

包含：

```text
ProposePlanAdaptationTool
```

更新：

```text
backend/app/tools/builtin/providers.py
```

注册三个新 Tool。

---

# 53. API Files

新增：

```text
backend/app/api/routes/plan_changes.py
```

并接入 Router。

API 只：

```text
authenticate
validate request
call application service
map result / errors
```

不能直接操作 ORM。

---

# 54. Tool Runtime Changes

扩展：

```text
ToolRisk
```

更新 ToolExecutor 授权：

```text
READ_ONLY → allow
ANALYZE   → allow
DRAFT     → allow
MUTATING  → deny model execution
```

保持 Phase 2 的：

```text
Registered
≠
Visible
≠
Executable
```

以及：

```text
run-local Discovery
trusted context
timeout
error normalization
```

不变。

---

# 55. Working Context

ContextAssembler 不新增业务计算。

仍然读取：

```text
Active Goal
Active Plan Summary
Latest Athlete State
```

Phase 3 后 Latest Athlete State 来自：

```text
AthleteStateEvaluatorV1
```

产生的正式 Snapshot。

Working Context 不触发：

```text
recompute()
```

---

# 56. Seed Strategy

保留 Phase 1 / Phase 2 的：

```text
seed-fixture AthleteStateSnapshot
```

以保证历史 Query Regression Test 仍然可独立验证。

Phase 3 Scenario：

```text
seed_vertical_slice()
↓
产生 fixture Snapshot V1

AthleteStateRecomputeService.recompute()
↓
产生 phase3.v1 Snapshot V2
```

此后：

```text
get_latest_athlete_state
```

与：

```text
WorkingContext
```

都必须看到：

```text
V2
algorithm_version = phase3.v1
```

不为了 Phase 3 删除旧测试所需 Fixture。

---

# 57. Vertical Slice Expected Result

现有 seed：

```text
2026-08-27

Interval

RPE = 8
subjective_fatigue = 7
soreness = 6

note =
最后两组间歇明显掉速
```

Phase 3 v1 应产生：

```text
fatigue_level = HIGH

recovery_level = FAIR

algorithm_version = phase3.v1
```

由于近期多次 Workout 只有最后一次拥有 RPE：

```text
training_load_coverage < 0.5
```

所以：

```text
recent_training_load = None
```

但：

```text
TrainingLoadAnalysis
```

仍然返回：

```text
partial_srpe_load
coverage
total_duration
total_distance
quality_session_count
```

这是正确行为。

不能为了让：

```text
recent_training_load
```

有数字而伪造缺失 RPE。

---

# 58. Plan Adaptation Vertical Slice

当前计划包含：

```text
2026-08-29 EASY

2026-08-31 TEMPO
```

当：

```text
Athlete State = HIGH fatigue
```

Agent 可以：

```text
search_tools
↓
get_active_plan
↓
propose_plan_adaptation(
    based_on_plan_version=1,
    based_on_state_version=2,
    horizon_days=7,
    reason="..."
)
```

Domain 生成：

```text
PlanChange DRAFT

8/31:
TEMPO
→
REST
```

当前：

```text
Plan V1
```

仍然 ACTIVE。

TurnCommitted 后：

```text
PlanChange
→
PENDING_CONFIRMATION
```

---

# 59. Confirmation Vertical Slice

用户显式确认：

```text
POST /api/v1/plan-changes/{id}/confirm
```

执行：

```text
freshness OK
↓
validation OK
↓
atomic activation
```

结果：

```text
Plan V1
SUPERSEDED

Plan V2
ACTIVE

PlanChange
CONFIRMED
```

V2 中：

```text
8/29 EASY
保持

8/31 TEMPO
→
REST
```

窗口外所有 Session：

```text
原样复制
```

所有新 PlannedSession 使用：

```text
new id
```

旧 Plan Sessions 永不 UPDATE。

---

# 60. Required Unit Tests

必须覆盖纯 Domain Logic：

```text
session-RPE calculation

missing RPE

load coverage

current / previous window

future evidence exclusion

fatigue HIGH rules

fatigue MODERATE rules

fatigue UNKNOWN

recovery POOR / FAIR / GOOD / UNKNOWN

confidence calculation

seed vertical-slice evaluation

Plan adaptation window

TEMPO → REST

INTERVAL → REST

RACE immutable

empty adaptation rejected

PlanChange validation
```

---

# 61. Required Integration Tests

必须覆盖：

```text
Snapshot append-only

version monotonic

same as_of idempotency

as_of rollback rejection

UserRow mutation lock semantics

cross-user isolation

TrainingPlan (user_id, version) uniqueness

PlanChange ownership

one unresolved PlanChange per user

freshness check

atomic Plan activation

old Plan → SUPERSEDED

new Plan → ACTIVE

duplicate confirmation idempotency
```

---

# 62. Required Scenario Tests

至少包括：

### Scenario 1 — Athlete State Recompute

```text
seed fixture V1
↓
recompute
↓
V2 phase3.v1
```

断言：

```text
fatigue = HIGH
recovery = FAIR
```

---

### Scenario 2 — Query Does Not Compute

没有 Snapshot：

```text
get_latest_athlete_state
→ None
```

不能自动调用 Evaluator。

---

### Scenario 3 — Analyze Training Load

Agent：

```text
search_tools
↓
analyze_training_load
```

Observation 包含：

```text
duration
distance
partial sRPE
coverage
```

---

### Scenario 4 — Hidden Analysis Tool

未 search：

```text
analyze_training_load
→ tool_not_available
```

---

### Scenario 5 — Analyze Workout

返回：

```text
Workout
Feedback
same-day Plan Context
session-RPE
```

不得返回：

```text
completed=true
```

---

### Scenario 6 — Proposal Does Not Activate

调用：

```text
propose_plan_adaptation
```

之后：

```text
PlanChange = DRAFT

Active Plan Version
不变
```

---

### Scenario 7 — TurnCommitted

Agent 成功 Final：

```text
DRAFT
→
PENDING_CONFIRMATION
```

---

### Scenario 8 — Failed Turn

Proposal 后：

```text
TurnFailed
```

结果：

```text
PlanChange = ABANDONED
```

---

### Scenario 9 — Cancelled Turn

同理：

```text
ABANDONED
```

---

### Scenario 10 — Confirm

```text
POST confirm
```

成功产生：

```text
Plan N+1
```

---

### Scenario 11 — Stale Plan

Proposal 基于：

```text
Plan V1
```

确认时：

```text
Active Plan = V2
```

结果：

```text
409
PlanChange = STALE
```

---

### Scenario 12 — Stale Athlete State

Proposal 基于：

```text
State V3
```

确认时：

```text
Latest = V4
```

结果：

```text
409
STALE
```

---

### Scenario 13 — Cross User

User B：

```text
GET / confirm
User A PlanChange
```

结果：

```text
404
```

---

### Scenario 14 — Duplicate Confirmation

同一 PlanChange confirm 两次：

```text
只创建一个 Plan Version
```

第二次返回：

```text
同一个 resulting_plan_id
```

---

### Scenario 15 — Race Safety

Adaptation Window 存在 Race：

```text
Race 不变化
```

---

### Scenario 16 — Phase 1 / 2 Regression

必须全部继续通过：

```text
Conversation
Transaction A/B
TurnCommitted

Runtime loop
ReasoningState

Native Tool Calling

Tool Discovery
Run-local Isolation

Trusted user_id

Hidden Tool rejection

SSE

Failed / Cancelled Turn
```

---

# 63. Implementation Order

Agent 必须按以下顺序实施。

## Step 0 — Baseline

先执行：

```text
pytest
ruff check .
```

记录 Phase 1 / 2 基线。

不得在已有失败测试上继续 Phase 3。

---

## Step 1 — Domain Models + Migration

先实现：

```text
PlanStatus.SUPERSEDED

AthleteState additional fields

AthleteStateSignal

PlanChange

PlanChangeStatus

DB migration
```

不先写 Tool。

---

## Step 2 — Evidence Query

扩展 Repository：

```text
list_between

batch feedback query
```

确保：

```text
end <= as_of
```

测试时间边界。

---

## Step 3 — Training Analysis

实现：

```text
TrainingLoadAnalysis
WorkoutAnalysis
```

全部纯 Deterministic Logic + Application Service。

---

## Step 4 — Athlete State

实现：

```text
AthleteStateEvaluatorV1
AthleteStateRecomputeService
append_snapshot
user-level mutation lock
```

完成 Phase 3 Vertical Slice State Test。

---

## Step 5 — Analysis Tools

增加：

```text
analyze_training_load
analyze_workout
```

扩展：

```text
ToolRisk
ToolExecutor policy
```

验证 Phase 2 Discovery 不回归。

---

## Step 6 — Plan Adaptation Domain

实现：

```text
reduce_upcoming_load

PlanChange payload generation

PlanChangeValidator
```

纯 Domain Test 先完成。

---

## Step 7 — Draft Tool

增加：

```text
propose_plan_adaptation
```

仅创建：

```text
DRAFT
```

---

## Step 8 — Lifecycle Integration

增加：

```text
TurnCommitted
→ pending

TurnFailed / Cancelled
→ abandoned
```

不得修改 AgentRuntime 主循环。

---

## Step 9 — Confirmation Boundary

增加：

```text
GET plan change

POST confirm

POST reject
```

实现：

```text
PlanActivationStore
```

完成：

```text
Freshness
Validation
Atomic Activation
Idempotency
```

---

## Step 10 — Scenario Regression

跑全部：

```text
Unit
Integration
Scenario
Phase 1
Phase 2
```

最后：

```text
ruff check .
```

---

# 64. Files That Must Not Absorb Phase 3 Logic

禁止为了“方便”把 Coaching Intelligence 塞进：

```text
agent/runtime/agent_runtime.py

agent/reasoning/*

agent/context/assembler.py

tools/executor/executor.py

api/routes/chat.py

infrastructure/database/repositories/*
```

Infrastructure Repository 只能：

```text
query
map
persist
transaction
locking
```

不能决定：

```text
fatigue
recovery
training advice
plan adaptation rule
```

---

# 65. No Compatibility Layer

禁止为了兼容旧设计保留：

```text
type-factor load
+
session-RPE load
```

两套正式负荷算法。

禁止同时存在：

```text
confirm_plan_adaptation Tool
+
HTTP Confirmation
```

两条激活路径。

禁止：

```text
recompute_athlete_state Tool
+
System Recompute
```

两套 State Mutation 路径。

Phase 3 只有一份正式语义。

---

# 66. Definition of Done

Phase 3 只有全部满足以下条件才算完成。

## Training Analysis

* [ ] session-RPE 计算确定
* [ ] Missing RPE 不被补值
* [ ] Coverage 正确
* [ ] as_of 上界正确
* [ ] 7d / previous-7d 可复现
* [ ] 分析结果明确 partial

## Athlete State

* [ ] `AthleteStateEvaluatorV1`
* [ ] `algorithm_version = phase3.v1`
* [ ] Seed Vertical Slice 得到 HIGH fatigue
* [ ] Recovery = FAIR
* [ ] Snapshot append-only
* [ ] Version 单调
* [ ] as_of 可追溯
* [ ] Evidence Signals
* [ ] Confidence
* [ ] Query path 不计算
* [ ] `workout_completion_rate = None`

## Tools

* [ ] `analyze_training_load`
* [ ] `analyze_workout`
* [ ] `propose_plan_adaptation`
* [ ] 全部保持 Dynamic Discovery
* [ ] 无 `recompute_athlete_state` Tool
* [ ] 无 `confirm_plan_adaptation` Tool

## Plan Adaptation

* [ ] 仅 `reduce_upcoming_load`
* [ ] 仅 `TEMPO / INTERVAL → REST`
* [ ] Race immutable
* [ ] Structured PlanChange
* [ ] DRAFT 与 Active Plan 分离
* [ ] TurnCommitted 后才 Pending
* [ ] Failed / Cancelled → Abandoned
* [ ] Explicit Confirmation API
* [ ] Plan Freshness
* [ ] Athlete State Freshness
* [ ] Atomic Plan Activation
* [ ] Plan N → SUPERSEDED
* [ ] Plan N+1 → ACTIVE
* [ ] Duplicate Confirm 幂等

## Architecture Regression

* [ ] AgentRuntime 主循环不改
* [ ] ChatService 生命周期所有权不改
* [ ] ContextAssembler 不计算状态
* [ ] ToolRuntime Discovery 语义不改
* [ ] Trusted ToolExecutionContext 不改
* [ ] Phase 1 tests 全绿
* [ ] Phase 2 tests 全绿
* [ ] Ruff 全绿

---

# 67. Final Acceptance Scenario

最终必须真实跑通：

```text
Runner Training Facts
        ↓
Training Analysis
        ↓
AthleteStateEvaluatorV1
        ↓
AthleteStateSnapshot V2
        ↓
Working Context
        ↓
Agent
        ↓
search_tools
        ↓
analyze_training_load
        ↓
get_active_plan
        ↓
propose_plan_adaptation
        ↓
PlanChange DRAFT
        ↓
FinalAction
        ↓
TurnCommitted
        ↓
PENDING_CONFIRMATION
        ↓
User Explicit Confirmation
        ↓
Freshness Check
        ↓
Domain Validation
        ↓
Atomic Activation
        ↓
Plan V1 SUPERSEDED
Plan V2 ACTIVE
```

当这条链真正成立后：

> **Phase 3 才算完成。**

此时 Run Coach 已经具备第一版真正的：

```text
Observe
↓
Understand
↓
Investigate
↓
Decide
↓
Propose
↓
Confirm
↓
Act
```

而 Memory 与长期 Learn Loop 留给后续 Phase。
