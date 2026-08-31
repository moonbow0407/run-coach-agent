# Phase 5 — Continuous State and Workers

> **Status:** Draft — Implementation Contract
> **Depends on:** `docs/ARCHITECTURE.md`, Phase 1–4
> **Scope:** Durable Business Events + Transactional Outbox + Redis Task Queue + Worker + Retry + Continuous Athlete State + Continuous Memory

---

# 1. Phase Goal

Phase 5 回答：

> **当新的训练事实、反馈和已提交对话持续进入系统时，Run Coach 如何自动、安全、可靠地持续更新自己的状态与长期认知？**

目标链路：

```text
Canonical State Change
        ↓ same PostgreSQL transaction
Durable Business Event in Outbox
        ↓
Outbox Publisher
        ↓
Redis Task Queue
        ↓
Worker
        ↓
Existing Application Service
        ↓
Versioned Athlete State / Long-term Memory / Episode
```

Phase 5 将 Phase 3 的 `AthleteStateRecomputeService` 与 Phase 4 的 Memory Projection Services 升级为持续执行模型。它不重新设计 Athlete State 算法或 Memory Domain，也不把模块化单体拆成微服务。

---

# 2. Current Limitations and Phase Transition

当前代码：

- FastAPI 与 PostgreSQL 已存在；`docker-compose.yml` 尚无 Redis，Python 依赖中没有 task queue。
- `LifecycleDispatcher` 是进程内事件总线。`publish_after_commit()` 发生在数据库提交后，listener 失败只记录日志。
- `TurnCommitted`、`TurnFailed`、`TurnCancelled` 是 Conversation lifecycle events；`ReasoningStarted`、`ToolStarted` 等是 runtime events。
- `PlanChangeLifecycleListener` 依赖 post-commit listener 把 DRAFT 提升为 PENDING 或在失败 / 取消后 ABANDONED，因此仍存在 commit 后进程崩溃导致状态未收尾的窗口。
- Phase 4 的 memory listener 同样只能 best-effort 调用幂等 Projection Service。
- `SqlAlchemyConversationStore.commit_turn()` 自己拥有 Transaction B，但目前不写 Outbox。
- `SqlAlchemyPlanActivationStore.confirm()` 已在 `UserRow FOR UPDATE` 下原子激活新计划，是写 `PlanChangeConfirmed` Outbox 的正确事务边界。
- `AthleteStateRecomputeService` 读取证据后由 Repository 在 append 阶段获取 UserRow lock；这个锁没有覆盖“读取 evidence → 计算 → append”的完整链，不能作为并发 Worker 的最终串行化保证。
- Athlete State append 已具有版本单调、`as_of` rollback rejection 和 same-as-of same-assessment idempotency，可作为 Phase 5 的领域保护基础。
- 当前 Workout / WorkoutFeedback 主要由 seed 和查询路径提供，尚无正式在线 mutation boundary；持续状态要求新增或明确实际 canonical write store，不能从 query repository 旁路发事件。

Phase transition：

```text
Phase 4 production in-process memory projection
        ↓ remove as owner
Phase 5 durable event + worker projection
```

```text
Phase 3 best-effort PlanChange terminal listener
        ↓ remove as owner
Phase 5 durable terminal-turn consumer
```

Lifecycle events 可以继续服务 SSE、日志与本进程进度，但不再承担需要可靠恢复的业务投影或 PlanChange 收尾。

---

# 3. Non-Goals

Phase 5 不实现：

- 通用 Event Bus、Event Sourcing、Saga、Workflow Engine、DAG scheduler 或通用任务平台。
- 微服务拆分、Kubernetes、跨地域队列、多数据中心一致性。
- 全系统 global ordering、exactly-once transport 或 Redis distributed lock framework。
- 新的 Memory 类型、Memory promotion 规则、Episode 语义或 Athlete State 算法。
- Workout deep analysis、Embedding batch pipeline、Eval batch；这些只保留未来 Worker 扩展空间。
- 完整 tracing / metrics platform、LLM evaluation、Safety evaluation 或实验平台。
- Garmin、Strava 等 external ingestion adapter；但其未来写入必须复用本 Phase 的 canonical mutation + outbox boundary。
- 十几个细粒度 task、queue adapter implementation test matrix 或 broker-specific abstraction framework。

---

# 4. Architecture Invariants

1. PostgreSQL business tables 仍是 Canonical State；Event 不是主要持久化模型。
2. 关键 business state mutation 与对应 Outbox row 必须在同一数据库事务内提交或回滚。
3. Queue 提供 at-least-once delivery；业务语义通过 idempotent service / consumer 实现 exactly-once logical result。
4. Outbox 是待发布 business event；Queue job 是运行调度状态；Consumer receipt 是处理结果。三者不能混成一张“万能任务表”。
5. Runtime / Lifecycle Event 与 Durable Business Event 必须明确区分，不能把全部 LifecycleEvent 写入 Outbox。
6. Worker task 只负责 contract validation、idempotency、retry、日志和调用 Application Service，不实现 Memory / Athlete State / Plan 业务规则。
7. API Process 与 Worker Process 使用同一代码库、Domain Contract、Application Service 与 PostgreSQL。
8. 数据库事务不得跨越 Redis、LLM、Embedding Provider 或其他外部调用。
9. transient、permanent、obsolete 和 poison message 有不同结果；不得全部无限 retry。
10. 不依赖 Queue 顺序保证 correctness；同一用户的最终语义由 UserRow lock、event time / evidence cutoff、append-only snapshot 和 service idempotency 保护。
11. 不需要全局排序，也不引入 Redis distributed lock；PostgreSQL 是当前模块化单体的并发事实边界。
12. `AthleteStateSnapshot.as_of` 来自 canonical evidence availability cutoff，不使用 Worker 执行时间伪造。
13. Phase 4 Memory Projection Service 的 Evidence、merge、supersession、projector version 与业务幂等语义保持不变。
14. 用户身份来自 durable envelope 中由可信 producer 写入的 `user_id`，consumer 仍必须用 canonical row 复核归属。
15. Phase 1–4 regression suite 必须继续通过。

---

# 5. Process and Module Boundary

部署形态：

```text
FastAPI Process
  ├── HTTP / SSE
  ├── ChatService / Coaching Application Services
  └── transactional outbox producers

PostgreSQL
  ├── canonical facts / state / memory
  ├── outbox_events
  └── event_consumptions

Redis
  └── ARQ durable task queue

Worker Process
  ├── outbox publisher cron
  ├── task consumers
  └── existing Application Services
```

建议目录：

```text
backend/app/workers/
├── __init__.py
├── settings.py
├── routing.py
├── contracts.py
├── publisher.py
├── consumer.py
└── tasks/
    ├── turn_terminal.py
    ├── athlete_state.py
    ├── semantic_memory.py
    └── episode.py

backend/app/infrastructure/outbox/
├── repository.py
└── writer.py

backend/app/infrastructure/queue/
└── arq_adapter.py
```

Durable payload 由事实所属模块定义，避免 worker 拥有业务事实：

```text
backend/app/common/events.py                 # provider-neutral envelope / metadata
backend/app/agent/contracts/durable_events.py
backend/app/coaching/contracts/durable_events.py
```

`common.events` 只提供最小 envelope primitives，不演化为通用 event framework。

---

# 6. Queue and Broker Decision

Phase 5 v1 选择：

```text
Redis 7
+ ARQ
```

原因：

- 当前代码是 Python 3.12 + async SQLAlchemy + FastAPI，ARQ 原生 asyncio，Worker 可以直接调用现有 async Application Services。
- 支持 Redis-backed queue、并发 Worker、job id、deferred execution 与 delayed retry。
- 比 Celery 的组件和配置面更小，符合本阶段有限任务范围；比自研 Redis list / stream consumer 少自定义可靠性代码。
- Redis 只保存 operational queue state，长期事实与业务幂等仍在 PostgreSQL。

不把 ARQ 类型泄漏到 Domain / Application。`QueuePublisher` Port 只接收 versioned `WorkerTaskEnvelope`；ARQ adapter 负责 `_job_id`、defer、serializer 与 broker exception mapping。

Redis 部署要求：

- 独立 service，开启 AOF 持久化；
- 明确 maxmemory policy，禁止静默淘汰 queue keys；
- health check 与 Worker readiness；
- Redis 丢失不改变 PostgreSQL canonical data；未完成事件可由 Outbox / recovery path 重投。

---

# 7. Runtime Lifecycle Event vs Durable Business Event

继续只在进程内发布、不写 Outbox：

```text
TurnStarted
ContextAssemblyStarted
ContextAssembled
ReasoningStarted
ReasoningCompleted
ToolStarted
ToolCompleted
TurnCommitStarted
```

它们表达执行进度、SSE、日志或 trace，不代表需要异步投影的 canonical business fact。

Phase 5 v1 durable events：

```text
conversation.turn_committed.v1
conversation.turn_failed.v1
conversation.turn_cancelled.v1

coaching.workout_changed.v1
coaching.workout_feedback_changed.v1
coaching.athlete_state_recomputed.v1
coaching.plan_change_confirmed.v1
```

说明：

- 三个 terminal Turn event 是 durable conversation facts。只有 committed 驱动 Memory；三者共同可靠收尾该 Turn 创建的 PlanChange DRAFT。
- `workout_changed` / `workout_feedback_changed` 使用 payload 中 `change_kind = RECORDED | UPDATED`，避免为相同行为复制事件类型。
- `athlete_state_recomputed` 只在真正追加新 Snapshot 的事务中产生；幂等 no-op 不产生第二个 event。
- `plan_change_confirmed` 与 plan activation 在同一事务中产生，用于 Episode Projection。
- 如果未来某 canonical mutation 没有可靠 downstream work，不要求机械写 Outbox。

现有同名 `TurnCommitted` lifecycle dataclass 仍可在 Transaction B 后发布给 SSE / logging adapter，但不能成为 production projection owner。Durable event 使用稳定字符串 contract，二者不可在代码中互相冒充。

---

# 8. Durable Event Contract

```text
DurableEventEnvelope

event_id: UUID
event_type: str
schema_version: int

aggregate_type: str
aggregate_id: UUID
user_id: UUID

occurred_at: datetime
payload: validated event-specific object

correlation_id: UUID
causation_id: UUID | None
trace_id: UUID | None
```

规则：

- `event_id` 由 producer 生成且全局唯一。
- `event_type + schema_version` 决定 payload schema；consumer 对未知 type / version fail permanently 并 quarantine。
- `aggregate_id` 表示发生变化的 canonical subject，不用 Redis job id 代替。
- `occurred_at` 表示该变化在 canonical transaction 中正式发生 / 可用的时间，不是 Worker 收到时间。
- payload 只携带稳定 identity、change kind 和必要时间 / version，不复制整行 ORM 或大型 Message content。
- consumer 通过 `user_id + aggregate_id` 重新读取 canonical state，并验证 event user 与 row owner 一致。
- correlation / trace metadata 来自可信 request / upstream event；模型或 HTTP body 不能注入。
- 所有时间使用带时区 UTC 表示，边界层负责展示时区。

## 8.1 Payload v1

```text
TurnCommittedV1
  turn_id
  thread_id
  user_message_id
  assistant_message_id
  run_id
  committed_at
```

```text
TurnFailedV1 / TurnCancelledV1
  turn_id
  thread_id
  run_id
  terminal_at
```

```text
WorkoutChangedV1
  workout_id
  change_kind
  source_fact_at
  available_at
```

```text
WorkoutFeedbackChangedV1
  feedback_id
  workout_id
  change_kind
  source_fact_at
  available_at
```

```text
AthleteStateRecomputedV1
  snapshot_id
  snapshot_version
  as_of
  algorithm_version
```

```text
PlanChangeConfirmedV1
  plan_change_id
  from_plan_id
  resulting_plan_id
  based_on_state_id
  confirmed_at
```

payload 不包含 Memory extraction output、embedding、完整 Workout、完整 Plan 或错误堆栈。

---

# 9. Transactional Outbox

新增表：

```text
outbox_events

id: UUID PK
event_id: UUID UNIQUE
event_type: str
schema_version: int

aggregate_type: str
aggregate_id: UUID
user_id: UUID

occurred_at: datetime
payload: JSONB
correlation_id: UUID
causation_id: UUID | None
trace_id: UUID | None

status: PENDING | PUBLISHED | QUARANTINED
available_at: datetime
claimed_by: str | None
claim_until: datetime | None
publish_attempt_count: int
last_error_code: str | None

created_at: datetime
published_at: datetime | None
quarantined_at: datetime | None
```

索引：

```text
UNIQUE(event_id)
INDEX(status, available_at, created_at)
INDEX(user_id, occurred_at)
INDEX(claim_until) WHERE status = pending
```

## 9.1 Atomic producers

以下 mutation 必须把 canonical change 与 Outbox row 写入同一 `AsyncSession` / transaction：

- `ConversationStore.commit_turn()` → `conversation.turn_committed.v1`；
- `ConversationStore.fail_turn()` → `conversation.turn_failed.v1`；
- `ConversationStore.cancel_turn()` → `conversation.turn_cancelled.v1`；
- canonical Workout record / update store → `coaching.workout_changed.v1`；
- canonical Feedback record / update store → `coaching.workout_feedback_changed.v1`；
- Athlete State append transaction → `coaching.athlete_state_recomputed.v1`；
- `PlanActivationStore.confirm()` → `coaching.plan_change_confirmed.v1`。

如果 transaction rollback：

```text
canonical change absent
+ outbox event absent
```

不能先 commit business row，再在 Application Service 中调用另一个 Repository 写 Outbox。

## 9.2 Current port changes required

为把 request correlation 写入同一事务，`ConversationStore.commit_turn / fail_turn / cancel_turn` 接收可信 `EventMetadata`；ChatService 仍拥有何时调用终态 transaction 的职责。这个签名扩展是可靠事件交付的 Architecture requirement，不改变 ChatService 的 lifecycle ownership。

Workout / Feedback 必须新增正式 mutation Application Service + Store；API、seed、未来 import adapter 只能走该入口。Query Repository 不发事件。

`PlanActivationStore` 与 Athlete State append store 内部复用 session-bound `OutboxWriter`；Domain / Application 不依赖 SQLAlchemy 或 Redis。

---

# 10. Outbox Publisher

Publisher 作为 Worker Process 中的 ARQ cron job 周期运行；不增加第三个长期服务进程。

算法：

```text
Transaction 1
  SELECT pending, available rows
  FOR UPDATE SKIP LOCKED
  claim bounded batch with lease
  increment publish_attempt_count
COMMIT

outside DB transaction
  validate durable event
  route to one or more WorkerTaskEnvelope
  enqueue each task to Redis

Transaction 2
  if all required enqueue acknowledgements succeeded:
      status = PUBLISHED
      published_at = now
      clear claim
  else:
      release / expire claim
      set available_at by backoff
      save safe error code
COMMIT
```

数据库事务不得覆盖 Redis enqueue。

如果 Publisher 在 enqueue 成功后、mark published 前崩溃，lease 到期后会再次 enqueue。Queue 与 consumer 必须允许重复；这是预期 at-least-once 语义。

Publisher transient errors 使用有上限的 exponential backoff。无法解析的 event type / schema 是 producer contract violation，标记 `QUARANTINED` 并告警，不无限 retry。Outbox row 不因 published 而立即删除；Phase 5 保留足够审计窗口，清理策略由以后 production hardening 决定。

---

# 11. Task Contract and Routing

```text
WorkerTaskEnvelope

task_name: str
task_version: int
event: DurableEventEnvelope
enqueued_at: datetime
```

Redis job id：

```text
{task_name}:{task_version}:{event_id}
```

ARQ job id 是 broker-level duplicate suppression，不能替代 Application Service 业务幂等。

Phase 5 v1 只有四类 worker task：

```text
finalize_terminal_turn
recompute_athlete_state
project_semantic_memory
project_episode
```

固定 routing：

```text
conversation.turn_committed.v1
  → finalize_terminal_turn
  → project_semantic_memory

conversation.turn_failed.v1
conversation.turn_cancelled.v1
  → finalize_terminal_turn

coaching.workout_changed.v1
coaching.workout_feedback_changed.v1
  → recompute_athlete_state

coaching.athlete_state_recomputed.v1
coaching.plan_change_confirmed.v1
  → project_episode
```

`finalize_terminal_turn` 只调用现有 Plan Adaptation Application Service：committed 时 DRAFT → PENDING_CONFIRMATION，failed / cancelled 时 DRAFT → ABANDONED。它不是新的 Plan 业务实现。

不为每个 event 建一个 actor，不支持任意 runtime 动态 routing，不让 task payload 指定可执行函数名。

---

# 12. Consumer Idempotency

新增表：

```text
event_consumptions

consumer_name: str
consumer_version: int
event_id: UUID
user_id: UUID

status: PROCESSING | COMPLETED | DEAD_LETTERED
attempt_count: int
lease_owner: str | None
lease_until: datetime | None
last_error_code: str | None
started_at: datetime
completed_at: datetime | None

PRIMARY KEY(consumer_name, consumer_version, event_id)
INDEX(status, lease_until)
INDEX(user_id, started_at)
```

该表是 consumer outcome / claim，不是 Queue job state，也不替代 Outbox。

处理规则：

1. 验证 Task / Event schema 与 routing。
2. 以 `(consumer_name, version, event_id)` 原子 claim；已 completed 直接 ack。
3. active lease 表示另一个 consumer 正在处理，当前 delivery 延后；stale lease 可接管。
4. 调用对应 Application Service。
5. service 成功或返回明确 obsolete / no-op 后标记 completed。
6. transient failure 更新 attempt / error，释放 claim 并由 ARQ delayed retry。
7. permanent failure 或达到最大尝试次数后标记 dead-lettered，ack Queue，保留 event / receipt 供人工诊断与显式 replay。

关键原则：

> Consumer receipt 与业务写入通常不是同一事务，因此 Application Service 自身必须幂等。

如果 service 已提交 Memory / Snapshot，但 Worker 在 receipt completed 前崩溃，下一次 delivery 会再次调用 service；Phase 3/4 的 idempotency 必须返回同一个逻辑结果。

---

# 13. Retry and Failure Classification

统一 typed outcome：

```text
SUCCESS
OBSOLETE_NOOP
TRANSIENT_FAILURE
PERMANENT_FAILURE
```

典型分类：

```text
PostgreSQL unavailable          → transient
Redis enqueue timeout           → publisher transient
LLM / Embedding timeout         → transient
provider rate limit             → transient
temporary lock / serialization  → transient

unknown event schema            → permanent / quarantine
canonical source missing        → permanent
event user != source owner      → permanent security failure
invalid domain state            → permanent
unsupported projector version   → permanent

older Athlete State trigger
already processed event
same projection result          → obsolete/no-op success
```

ARQ task v1 最大 8 次尝试，建议 delayed retry：

```text
5s, 30s, 2m, 10m, 30m, 2h, 6h
```

加入 bounded jitter，避免 provider / database 恢复时惊群。达到上限进入 durable dead-letter receipt，不无限 retry。未知异常在 worker boundary 归一化为安全内部错误，但不得用宽泛 catch 把 programming invariant 误判为成功。

人工 replay 必须显式指定 `event_id + consumer_name + consumer_version`，保留原 event identity；不能创建新 event 来掩盖旧失败。

---

# 14. Continuous Athlete State

目标：

```text
Workout record / update
WorkoutFeedback record / update
        ↓ durable event
recompute_athlete_state task
        ↓
AthleteStateRecomputeService
        ↓
append-only Snapshot Vn+1 or obsolete no-op
```

## 14.1 Time semantics

必须区分：

```text
source_fact_at
= 训练实际发生 / 用户反馈所描述的业务时间

available_at / occurred_at
= canonical fact 本版本提交、可被系统使用的时间

projection as_of
= 本 Snapshot 所使用 canonical evidence 的最大 availability cutoff

worker_started_at
= operational execution time，不进入 Athlete State 业务语义
```

晚导入的历史 Workout 在今天提交：`source_fact_at` 是历史训练时间，`available_at` 是今天；新 Snapshot 的 `as_of` 至少是今天的 canonical evidence cutoff。Worker 几小时后运行不能把几小时后的执行时间当作 `as_of`。

Workout 与 WorkoutFeedback canonical rows 必须具有可信 `created_at` / `updated_at`（或等价 version availability time）。Phase 5 migration 为缺少的更新语义补齐字段；update mutation 与 event 共用同一个 timestamp。

## 14.2 Per-user recompute transaction

为处理并发 Worker，Phase 5 将现有 recompute persistence seam 收紧为 `AthleteStateRecomputeUnitOfWork` Port：

```text
BEGIN
lock UserRow FOR UPDATE
read latest Snapshot
read current canonical Workout / Feedback evidence
calculate max evidence availability cutoff

if cutoff <= latest.as_of and no algorithm-version migration:
    return OBSOLETE_NOOP

run deterministic Training Analysis / Evaluator
append Snapshot Vn+1 with as_of = cutoff
insert AthleteStateRecomputed outbox event
COMMIT
```

Evaluator 是纯本地确定性逻辑，可以在这个短事务内执行；事务中不得调用 LLM、Embedding、Redis 或外部 API。

这个重构是 concurrency requirement：当前代码只在 append 阶段锁用户行，无法保证多个 Worker 的 evidence read 与 append 属于同一串行化边界。Application Service 保持唯一业务实现；Worker 不复制 fatigue / recovery 算法。

## 14.3 Ordering outcome

- 不依赖 Redis FIFO 或全局序号。
- 同一用户事件被 UserRow lock 串行化。
- 多个 pending changes 可以被一次最新 evidence recompute 合并。
- 较旧 event 后到时发现 cutoff 已覆盖，返回 obsolete no-op，不创建旧 Snapshot 覆盖新结果。
- Snapshot 继续 append-only、version monotonic、`as_of` non-decreasing。

---

# 15. Continuous Memory and Episodes

## 15.1 Semantic Memory

```text
conversation.turn_committed.v1
        ↓
project_semantic_memory
        ↓
SemanticMemoryProjectionService.project_committed_turn(
    user_id,
    turn_id,
    projector_version
)
```

failed / cancelled durable events 永远不路由到 Memory Projection。Consumer 重读 canonical committed Turn；不能只信 payload 文本，因为 payload 根本不携带文本。

Phase 4 的 stable projection key、独立 Memory / assertion identity、Evidence uniqueness、event-time correction precedence 与用户行锁 merge 保证重复 / 乱序 delivery 不产生重复或旧事实覆盖新纠正。projector version 只影响 ProjectionRun provenance，不能绕过 active slot uniqueness。

## 15.2 Episode

```text
AthleteStateRecomputed
PlanChangeConfirmed
        ↓
project_episode
        ↓
EpisodeProjectionService reevaluates bounded evidence window
```

两个 trigger 可能覆盖同一历史窗口；Phase 4 类型特定 stable Episode anchor / logical key 保证跨 projector version、跨新增 outcome evidence 仍只形成一个现实 Episode。无完整 outcome 时保持 building；后来 recovery Snapshot 到达后更新并完成同一 Episode。

Phase 5 不修改 Episode type、Evidence role、importance 或 Retrieval policy。

## 15.3 Production owner switch

Phase 5 完成后：

- 删除 / 取消装配 Phase 4 production `MemoryProjectionLifecycleListener`；
- 删除 / 取消装配 Phase 3 `PlanChangeLifecycleListener` 的 business mutation 职责；
- 保留 LifecycleDispatcher 给 SSE、logging、trace 等 runtime adapter；
- 不同时维护 in-process projection 与 Worker projection 两条 production owner 路径。

---

# 16. Canonical Mutation Boundaries

## 16.1 Conversation

Transaction B：

```text
assistant Message insert
Turn → COMMITTED
AgentRun → COMPLETED
TurnCommitted outbox insert
COMMIT
```

fail / cancel transaction 同样原子写 terminal state + durable event。Transaction A / Agent Runtime / current input 语义不变。

## 16.2 Workout / Feedback

新增正式 write Application Services：

```text
WorkoutCommandService.record / update
WorkoutFeedbackCommandService.record / update
```

它们调用 transaction-owning Store，在同一事务中验证 user ownership、写 canonical row / version time、写 Outbox。Phase 5 不要求新增外部 Training Integration，但 seed 和未来 adapter 不能再通过 ORM 旁路正式 mutation path 来模拟在线变化。

## 16.3 Plan activation

现有 `PlanActivationStore.confirm()` transaction 在成功创建 Plan N+1、旧 Plan superseded、PlanChange confirmed 后插入 `PlanChangeConfirmed` Outbox。重复 confirm 返回原 `resulting_plan_id`，不写第二个 event。

---

# 17. User Isolation and Security

- Outbox `user_id` 由 trusted producer 从 RequestContext / canonical row 得出，不接受模型或任意 task payload覆盖。
- Publisher 不改变 user identity，只封装已验证 event。
- Consumer 使用 event user 读取 canonical source，并核对 row owner；不匹配是 permanent security failure。
- Task Application Service 的 repository query 继续显式包含 `user_id`。
- 同一 task 不能用一个用户的 event ids 读取另一个用户的 Memory、Workout、Feedback、Snapshot 或 PlanChange。
- queue logs 不记录 message content、Memory content、JWT、LLM key、embedding 或完整 event payload。
- dead-letter error 保存安全 code / 摘要，不保存数据库连接串或 traceback。

---

# 18. Observability Boundary

Phase 5 每次发布 / 执行至少记录 structured fields：

```text
event_id
event_type
schema_version
task_name
task_version
consumer_name
user_id
correlation_id
trace_id
attempt
worker_id
duration_ms
status
error_code
```

必须能回答：

- business transaction 是否生成 Outbox；
- Outbox 是否 pending / claimed / published / quarantined；
- 哪些 tasks 被路由；
- consumer 是否 processing / retrying / completed / dead-lettered；
- service 最终产生了哪个 Snapshot / Memory / Episode，或为何 obsolete no-op。

Phase 5 不实现 dashboard、distributed tracing backend、业务质量 Eval 或复杂指标平台。结构化日志与数据库状态足以进行第一版运维诊断。

---

# 19. Persistence and Migration

Migration：

```text
0005_phase5_continuous_state_workers.py
```

新增：

```text
outbox_events
event_consumptions
```

修改：

- Workout / WorkoutFeedback 如果缺少 `updated_at` / availability version time，则新增并以现有 `created_at` 回填。
- 必要的 Outbox FK 只引用 `users`；event aggregate 是多态 identity，不建立跨所有业务表的单一 FK。
- 不修改 Phase 4 Memory lifecycle / Evidence schema。

约束：

```text
outbox event_id unique
event consumption composite primary key
attempt_count >= 0
claim / lease time consistency checks
known status check constraints
```

不创建 queue_jobs、queue_retries、generic_workflows 或 event_store 表。ARQ operational state 留在 Redis。

---

# 20. Worker Downtime and Recovery

## Publisher / Worker 停止数小时

```text
API continues committing canonical state + outbox rows
        ↓
outbox remains PENDING
        ↓
Worker restarts
        ↓
publisher claims and enqueues backlog in bounded batches
        ↓
consumers invoke idempotent services
        ↓
state / memory eventually catch up
```

## Worker 在 task 中崩溃

- active receipt lease 到期；
- ARQ redelivery 或 recovery enqueue 触发接管；
- 如果 service 尚未提交则重做；
- 如果 service 已提交但 receipt 未完成，业务 service 幂等返回已有逻辑结果；
- 最终只产生一个 logical Snapshot / Memory / Episode。

## Publisher 在 enqueue 后崩溃

- outbox claim lease 到期；
- 再次 enqueue 相同 deterministic job id；
- 即使 broker 已接受第一次任务，consumer idempotency 仍保证安全。

## Redis 数据丢失

Redis 不是 source of truth。Phase 5 提供 recovery command / scanner：对 `PUBLISHED` outbox event 中尚无 required completed / dead-letter receipt 且超过安全时间窗的 consumer route，使用原 event id 重新 enqueue。该操作可以重复，不创建新 business event。

---

# 21. Migration, Deployment, Fixtures, Rollback

## Deployment order

1. 部署 PostgreSQL migration 与兼容旧同步路径、尚未启用 Worker routing 的应用版本。
2. 启动 Redis（AOF）并验证 health / no-eviction policy。
3. 部署 Worker 与 Publisher，先保持消费开关关闭，验证 schema / routing。
4. 启用 durable producer + consumer owner。
5. 移除 production in-process memory projection 与 PlanChange terminal mutation listener。

切换必须是明确 owner handoff，不长期双写。

## Existing data and fixtures

- 不为历史 rows 伪造 outbox event；migration 前事实不会自动假装“刚发生”。
- 需要追上历史 State / Memory 时使用显式 bootstrap command，生成带清晰 causation 的 rebuild task，而不是偷偷 backfill event history。
- Phase 1–4 fixtures 保持可读。新增 continuous scenarios 必须通过正式 mutation services 产生 Outbox，不能直接 insert business row 后再手写 queue job。
- seed 可以保留直接构建静态历史 fixture 的能力，但凡测试“持续更新”必须走正式 writer。

## Rollback

- 先暂停 durable producers，再排空 / 停止 Publisher 与 Worker。
- 保留 `outbox_events` / `event_consumptions` 数据备份；Redis job 可丢弃，因为 PostgreSQL 可重建未完成工作。
- 回滚到 Phase 4 时，只能显式重新启用 best-effort listener 作为临时版本回退，不能让两种 owner 同时运行。
- schema downgrade 不应删除 canonical business rows、Memory 或 Athlete State；删除 Outbox / receipt 前必须确认不再需要恢复。

---

# 22. Acceptance Strategy

测试是 Contract 的支持证据。Phase 5 只新增七个高价值 acceptance scenarios，不围绕 ARQ adapter、每个 retry branch、每个 repository 方法或每个 status transition 创建几十个测试。

可靠性场景优先使用真实 PostgreSQL 与真实 Redis / ARQ integration environment。fake queue 只用于纯 routing contract，不得用 mock `enqueue()` 成功来证明 outbox atomicity、duplicate delivery 或 downtime recovery。

## Scenario 1 — Business transaction and outbox atomicity

通过正式 Chat commit 和 WorkoutFeedback mutation 分别验证 canonical row 与正确 versioned Outbox 同时可见。故意在 transaction 中制造失败，断言 canonical change 与 Outbox 均回滚。重复 PlanChange confirm 不产生第二个 confirmed event。

## Scenario 2 — Duplicate delivery produces one logical result

对同一个 TurnCommitted event 和同一个 Feedback event 重复 / 并发投递。断言只有一个逻辑 Semantic Memory / projection receipt，并且 Athlete State 只有符合 evidence cutoff 的一个新逻辑版本；consumer receipt 最终 completed，重复 delivery 为 no-op。

## Scenario 3 — Transient retry and permanent quarantine

让 embedding / database boundary 第一次返回 typed transient failure，验证 delayed retry 后最终成功且没有重复业务结果。再投递一个未知 schema 或跨用户 source event，验证不无限 retry、记录 dead-letter / quarantine 和安全 error code。

## Scenario 4 — Continuous Athlete State with trustworthy time

记录 / 更新 WorkoutFeedback，等待 Worker 调用现有 Evaluator 并产生 Snapshot Vn+1。断言 `as_of` 等于 canonical evidence availability cutoff，而非 Worker 执行时间；晚导入历史 Workout 仍进入新的当前 Snapshot，旧 trigger 后到不会产生 as_of rollback。

## Scenario 5 — Continuous Memory and Episode vertical slices

committed chat turn 自动形成 active Semantic Memory；failed / cancelled terminal events只收尾 PlanChange，不产生 Memory。随后 confirmed PlanChange + later recovery Snapshot 自动完成并检索同一个 Episode；两个 trigger 不产生重复 Episode。

## Scenario 6 — Downtime and eventual recovery

在 Publisher / Worker 停止时提交多个 canonical changes，确认 Outbox 保留 pending。重启后 backlog 被发布、重试并最终追上；另模拟 enqueue 后 publisher 崩溃与 service commit 后 consumer 崩溃，最终仍为 exactly one logical result。

## Scenario 7 — Same-user concurrency and cross-user isolation

同一用户短时间并发记录 Workout、Feedback、确认 PlanChange，打乱 queue delivery。断言 UserRow serialization、cutoff / append semantics 与 Memory event-time merge 阻止旧 projection 覆盖新结果；同时运行 User B 的相似事件，任何 task、Evidence、Snapshot、Memory、Episode 均不串用户。

## Focused tests only

只为以下非平凡确定性逻辑增加少量 focused tests：

- event schema version validation 与固定 routing；
- retry classification / backoff 上界；
- evidence availability cutoff / obsolete event decision。

不要求为 task wrapper、DTO、dataclass、Outbox row mapping、ARQ configuration、dependency wiring 或简单 receipt getter 编写单元测试。

现有 Phase 1–4 regression suite 必须继续通过。只在新异步 owner 现实可能破坏旧不变量时增加回归断言，例如 Transaction B、PlanChange terminal status、Snapshot append-only、current input exactly once 与 user isolation；不复制旧测试。

---

# 23. Implementation Order

1. **Baseline and contract review**：运行 Phase 1–4 tests / lint，确认当前 transaction owner、locks 与 Memory services。
2. **Durable event contracts**：实现最小 envelope、七个 versioned business event payload 与严格 validation。
3. **Outbox schema / writer**：Migration、session-bound writer、atomic producer integration；先证明 rollback invariant。
4. **Conversation and Plan owner transition**：Transaction B / fail / cancel / plan activation 同事务写 event，扩展可信 EventMetadata。
5. **Workout / Feedback mutation boundary**：新增正式 command + transaction store 与 availability timestamp，不先接外部平台。
6. **Redis / ARQ adapter**：依赖、配置、AOF/no-eviction、health、deterministic job id。
7. **Outbox publisher**：SKIP LOCKED claim、lease、外部 enqueue、mark published、publisher retry / quarantine。
8. **Consumer receipt / runner**：claim、lease、typed outcome、delayed retry、dead letter、replay。
9. **Athlete State concurrency seam**：实现 user-locked Recompute UoW、evidence cutoff、snapshot + outbox atomic append。
10. **Task adapters**：依次接入 `finalize_terminal_turn`、`recompute_athlete_state`、`project_semantic_memory`、`project_episode`；每个只调用 Application Service。
11. **Production owner switch**：关闭并删除 in-process Memory / PlanChange terminal business listeners，保留 lifecycle SSE / logs。
12. **Recovery / observability**：backlog、receipt、re-enqueue command 与 structured logs。
13. **Acceptance evidence**：完成七个真实 PostgreSQL + Redis 场景，运行 Phase 1–4 regressions。
14. **Independent review**：由未实现该 Phase 的 reviewer 对照 Architecture、Phase Contract 与代码检查 transaction、幂等和故障恢复。

不得先写十几个 actors，再反推事件语义；不得用 mock queue test 替代 Outbox transaction evidence。

---

# 24. Definition of Done

Phase 5 完成必须同时满足：

- [ ] durable business event 与 runtime lifecycle event 在 contract、存储和 owner 上明确分离。
- [ ] 所有列出的 canonical mutations 与 Outbox 在同一 transaction commit / rollback。
- [ ] Outbox Publisher 不跨 Redis 持有数据库事务，并支持 claim lease、retry 与 crash recovery。
- [ ] Redis + ARQ 只承担 operational queue state；PostgreSQL 保持事实、Memory、Outbox 与消费结果 source of truth。
- [ ] 四个 v1 tasks 只调用既有 / 正式 Application Services，不复制业务规则。
- [ ] duplicate / concurrent delivery 产生 exactly one logical business result。
- [ ] transient failure 有 bounded delayed retry，permanent / poison event 被 durable quarantine / dead-letter，不无限循环。
- [ ] Workout / Feedback 变化持续触发 Athlete State，`as_of` 使用 canonical evidence availability cutoff。
- [ ] TurnCommitted 持续触发 Semantic Memory；State / confirmed PlanChange 持续触发 Episode projection。
- [ ] 同一用户并发事件不能导致旧 Snapshot / Memory 覆盖较新语义，不引入 Redis distributed lock。
- [ ] Worker / Publisher 停机后能够从 PostgreSQL Outbox 与 Redis backlog 最终追上。
- [ ] production in-process projection 与 PlanChange terminal business listener 已移除，不存在双 owner。
- [ ] 七个 critical acceptance scenarios 通过，关键可靠性使用真实 PostgreSQL + Redis integration evidence。
- [ ] 现有 Phase 1–4 regression suite 继续通过。
- [ ] implementation notes 记录 event / task versions、部署切换、retry / dead-letter、恢复命令与已知限制。
- [ ] 独立 code / design review 对照 Architecture、Phase Contract 与实际代码后，没有 unresolved blocker。

“Worker 与实现 Agent 自己编写的测试全部通过”不能单独证明可靠性或 Phase 完成。

---

# 25. Final Acceptance Scenarios

## Scenario A — Committed conversation to durable Memory

```text
User completes chat turn
        ↓
Transaction B:
  assistant Message
  Turn COMMITTED
  AgentRun COMPLETED
  TurnCommitted outbox event
        ↓ COMMIT
Outbox Publisher
        ↓
project_semantic_memory task
        ↓
SemanticMemoryProjectionService
        ↓
ACTIVE Memory + canonical Evidence
```

## Scenario B — Feedback to continuous Athlete State

```text
WorkoutFeedback recorded / updated
        ↓ same transaction
FeedbackChanged outbox event
        ↓
recompute_athlete_state task
        ↓
user-locked evidence read + evaluator + append
        ↓
AthleteStateSnapshot Vn+1
as_of = canonical evidence availability cutoff
        ↓ same transaction
AthleteStateRecomputed outbox event
```

## Scenario C — Failure and recovery

```text
Worker first execution fails transiently
        ↓
receipt remains recoverable
+ delayed retry
        ↓
service eventually commits
        ↓
Worker crashes before receipt completion
        ↓
duplicate delivery
        ↓
service-level idempotency returns existing result
        ↓
receipt COMPLETED
exactly one logical result
```

三条链真实成立，Worker 停机后能够追上，并且 independent review 未发现 transaction / user isolation / ordering blocker 后，Phase 5 才具备交付资格。

---

# 26. Phase Boundary and Future Space

```text
Phase 4 owns:
  Memory semantics
  explicit / inferred rules
  lifecycle / correction
  Evidence
  projection Application Services
  retrieval / context integration
  business idempotency
```

```text
Phase 5 owns:
  durable triggering
  transactional outbox
  queue / worker execution
  consumer idempotency
  retry / dead letter / recovery
  continuous Athlete State / Memory / Episode invocation
```

Phase 5 不重新定义 Phase 4 Memory，也不改变 Phase 3 fatigue、recovery、Plan Adaptation 或 confirmation semantics。后续 Phase 仍保留清晰空间实现 Eval、Safety Evaluation、Observability Expansion、Production Hardening、External Training Integrations 与 Frontend Productization。
