# Phase 4 — Long-term Memory

> **Status:** Draft — Implementation Contract
> **Depends on:** `docs/ARCHITECTURE.md`, Phase 1–3
> **Next:** `docs/phases/PHASE_5_CONTINUOUS_STATE_AND_WORKERS.md`
> **Scope:** Long-term Memory Semantics + Evidence + Persistence + Projection + Retrieval + Context Integration

---

# 1. Phase Goal

Phase 4 回答：

> **Run Coach 如何长期认识一个具体跑者，并在未来决策中使用过去真正相关的信息？**

完成后，每次新的 Agent Run 可以获得：

```text
Current Goal
+ Current Plan
+ Latest Athlete State
+ Recent Committed Conversation
+ Relevant Semantic Memory
+ Relevant Historical Episodes
        ↓
Agent Runtime
```

Phase 4 首先证明 Memory 的领域语义、证据链、写入规则和检索价值正确。投影暂时可以由进程内 `TurnCommitted` listener、显式 Application Service 或维护命令触发；可靠异步交付、Worker、重试与持续投影属于 Phase 5。

Phase 4 只编写 Memory 能力，不重构 Agent Runtime，不把 Memory 变成第二份 Coaching 数据库。

---

# 2. Current Implementation Findings

当前代码已经提供以下稳定接缝：

- `ContextBundle.semantic_memories` 与 `ContextBundle.episodic_memories` 已存在。
- `MemoryContextProvider` 已是 `ContextAssembler` 的独立依赖；当前生产装配使用 `NullMemoryContextProvider`。
- `MemoryView` 与 `EpisodeView` 已存在，但字段不足以向 Reasoner 表达来源语义、有效期和重要性。
- `ContextAssembler` 已保证 `current_input` 独立于历史 committed conversation，且只出现一次。
- `ConversationReader.list_committed_messages()` 只读取 committed Turn，并排除 failed / cancelled Turn。
- `TurnCommitted` 包含 `user_id`、`turn_id`、两个 canonical message id、`run_id` 与 `committed_at`。
- `TurnFailed`、`TurnCancelled` 已有明确终态；失败或取消不会产生 committed assistant message。
- `LifecycleDispatcher.publish_after_commit()` 是 best-effort：listener 失败只记录日志，进程崩溃窗口仍存在。
- `AthleteStateRecomputeService`、版本化 `AthleteStateSnapshot`、`PlanChange` 与确认后的版本化 Plan 已存在，可作为 Episode 的 approved durable Evidence source。
- `UserRow FOR UPDATE` 已是同一用户 Domain Mutation 的并发边界。

Phase 4 必须补齐的接缝：

- 增加按 `user_id + turn_id` 读取一个 committed Turn 的 canonical user / assistant messages 的只读 Port；Projector 不得读取 RunStep 或 ReasoningState 还原对话。
- 新增正式 `memory` 模块、持久化模型、Evidence 校验、Projection Application Services、Embedding Port 与 Retrieval Service。
- 正式装配必须从 `NullMemoryContextProvider` 切到真实 Provider。Null 实现只可作为窄测试替身，不能继续作为生产 fallback。
- Phase 4 的进程内触发失败可能导致延迟或遗漏，必须可通过相同 source identity 手动重放；Phase 5 负责消除该可靠性缺口。

---

# 3. Non-Goals

Phase 4 不实现：

- Queue、Redis task broker、Worker、Transactional Outbox、delayed retry 或 dead letter。
- 通用 Event Platform、Workflow Engine、Event Sourcing 或微服务拆分。
- Eval Framework、LLM-as-a-Judge、Golden Dataset、实验平台或完整 Observability。
- Garmin、Strava、MCP、Multi-Agent 或外部训练平台接入。
- `write_memory` / `remember_this` Tool；Agent Runtime 不能直接写正式 Memory。
- 通用知识图谱、任意字符串 Memory type、无限自动 Episode 发现。
- 把 Workout、WorkoutFeedback、Goal、TrainingPlan、PlanChange 或 AthleteStateSnapshot 复制进 Memory。
- 存储隐藏 Chain of Thought、ReasoningState、ToolCall 或 Observation 作为 Memory 内容。
- 医疗诊断或基于模型推测形成医疗长期事实。

---

# 4. Architecture Invariants

1. Canonical Facts、Derived State、Long-term Memory 与 Runtime State 必须分离。
2. `SemanticMemory` 描述长期个人特征；`Episode` 描述有时间范围和未来决策价值的历史经历。
3. Memory 只能引用 approved durable evidence source，不能替代或修改 Evidence source。
4. 每条 Memory / Episode 必须至少有一条可验证且属于同一用户的 Evidence。
5. `AgentRuntime`、`ContextAssembler`、`ToolExecutor` 和 Reasoner 不写 Memory。
6. Projection 与 Retrieval 是两个独立 Application Boundary；读取 Context 不产生 Memory 写入。
7. Conversation Projection 只消费 committed Turn。failed / cancelled / running Turn 不可投影。
8. assistant message 可帮助理解语境，但不能作为“用户明确事实”的主要证据。
9. explicit 与 inferred 使用不同的来源、置信度和晋升规则；一次模型推断不得成为高置信长期事实。
10. 同一用户、同一主题不能同时存在互相冲突的 active Memory。
11. superseded Memory 保留历史和 Evidence，不物理覆盖或删除。
12. 所有查询、关联校验、合并和检索都必须显式带 `user_id`。
13. Projection 从第一天支持幂等重放，为 Phase 5 的 at-least-once delivery 做准备。
14. Memory Context 有严格数量与文本预算；完整 Evidence Graph 不进入 `ContextBundle`。
15. Phase 1–3 的 Conversation、Tool、Athlete State 与 Plan Adaptation 语义保持不变。
16. 当前 Turn 的 explicit user input 高于与其冲突的历史 Memory；更新的 canonical WorkingContext 高于冲突 Memory。Memory 是辅助认知，不能覆盖当前事实或尚未投影的用户纠正。

---

# 5. Ownership and Module Boundary

采用当前仓库的 Domain / Application / Ports 风格：

```text
backend/app/memory/
├── __init__.py
├── domain/
│   ├── semantic.py
│   ├── episode.py
│   ├── evidence.py
│   └── lifecycle.py
├── application/
│   ├── semantic_projection_service.py
│   ├── episode_projection_service.py
│   ├── retrieval_service.py
│   └── lifecycle_service.py
├── ports/
│   ├── repositories.py
│   ├── extractor.py
│   ├── embedding.py
│   └── evidence_reader.py
└── context_provider.py
```

Infrastructure：

```text
backend/app/infrastructure/database/
├── models/memory.py
└── repositories/memory.py

backend/app/infrastructure/memory/
├── extraction.py
└── embedding.py

backend/app/infrastructure/lifecycle/
└── memory_projection_listener.py
```

不为目录图创建空层。只有在对应行为实现时才创建文件。

`memory` 拥有 Memory 语义、合并、生命周期、Projection 与 Retrieval。`agent` 只提供 committed conversation 读取 Port 和 Context 接缝；`coaching` 继续拥有所有训练事实与 Athlete State。

---

# 6. Semantic Memory Model

`SemanticMemory` 回答：

> **这个跑者长期是什么样的人？**

正式模型：

```text
SemanticMemory

id: UUID
user_id: UUID

type: SemanticMemoryType
origin: EXPLICIT | INFERRED

subject_key: str
value: JSON scalar / bounded structured value
content: str

confidence: float
status: CANDIDATE | ACTIVE | SUPERSEDED | EXPIRED

valid_from: datetime
valid_until: datetime | None
activated_at: datetime | None
expired_at: datetime | None

projector_name: str
projector_version: str
embedding_model: str
embedding_version: str
embedding: vector

superseded_by_id: UUID | None
superseded_at: datetime | None

created_at: datetime
updated_at: datetime
```

字段语义：

- `type` 是有限枚举，不接受任意字符串。
- `subject_key` 标识同一 type 内可比较、可冲突的主题，例如 `weekly:wednesday:evening` 或 `preferred_training_time`。
- `value` 保存用于确定性去重和冲突判断的规范化断言；`content` 是给人和 Reasoner 阅读的简洁陈述。
- `content` 不能复制整条消息、整个 Turn、整份计划或完整状态快照。
- `origin` 表达认知来源，不等同于 Evidence 的对象类型。
- `confidence` 表达当前断言被证据支持的强度，不表达医学概率或模型自信。
- `valid_from` / `valid_until` 表达业务有效期，不等同于记录创建时间。
- `activated_at` / `superseded_at` / `expired_at` 表达系统何时开始或停止把该记录作为正式认知使用；它们不等同于业务有效期或 Evidence 发生时间。
- `projector_version` 必须能够定位产生该条 Memory 的 Projection Logic。

## 6.1 SemanticMemoryType v1

Phase 4 v1 精确支持八类：

```text
AVAILABILITY_CONSTRAINT
SCHEDULE_PREFERENCE
TRAINING_PREFERENCE
ENVIRONMENT_PREFERENCE
GOAL_PREFERENCE
RECOVERY_PATTERN
TRAINING_RESPONSE_PATTERN
COMMUNICATION_PREFERENCE
```

边界：

- `AVAILABILITY_CONSTRAINT`：长期或周期性不能训练的时间约束；一次性“今天没空”不是长期 Memory。
- `SCHEDULE_PREFERENCE`：软性的训练时段或周安排偏好，不等同于不可违反的 constraint。
- `TRAINING_PREFERENCE`：训练表达或课型偏好，例如按距离而不是按时间。
- `ENVIRONMENT_PREFERENCE`：跑步机、户外、场地、天气等环境偏好。
- `GOAL_PREFERENCE`：在正式 TrainingGoal 之外的长期目标取舍，例如更重视完赛体验；不能复制 Goal。
- `RECOVERY_PATTERN`：多次证据显示的恢复模式。
- `TRAINING_RESPONSE_PATTERN`：对训练刺激的重复反应模式。
- `COMMUNICATION_PREFERENCE`：解释深度、表达风格等教练交互偏好。

新增类型必须由后续 Phase Contract 修改枚举、验证规则与检索策略，不能只让模型输出一个新字符串。

## 6.2 Type-specific assertion validation

Extractor 输出 `type + subject_key + value + content` 后必须经过确定性验证：

- `subject_key` 使用小写、有限长度、稳定 token，不包含用户文本原文或 PII blob。
- `value` 只允许布尔、有限字符串、数字或小型结构；拒绝无界 JSON 和嵌套自由文本。
- 同一 `type + subject_key + normalized(value)` 计算 `assertion_hash`。
- 同一 `type + subject_key` 但不同规范化 value 表示潜在冲突。
- type-specific validator 负责拒绝不合法组合；LLM 输出不是 Domain Authority。

---

# 7. Explicit and Inferred Semantics

## 7.1 Explicit

Explicit 表示用户在 canonical user message 中明确表达的长期事实、约束或偏好。

规则：

- primary evidence 必须包含 user `Message`；assistant message 不能单独支持 explicit Memory。
- 只有具有持续、重复、周期或明确未来有效语义的表达才进入 Memory。
- 明确但有结束时间的表达写入 `valid_until`，不能被提升为永久事实。
- 清晰且通过 Domain Validation 的 explicit Memory 直接进入 `ACTIVE`，`confidence = 1.0`；这里的 1.0 表示“用户明确这样陈述”，不是客观世界永远为真。
- 含糊、反问、引用他人、假设、玩笑、助手复述或一次性临时安排不创建 active Memory。

## 7.2 Inferred

Inferred 表示系统根据多个正式证据推断出的重复模式。

规则：

- 一次 Workout、一次 Feedback、一次 Episode 或一次模型判断最多创建 / 更新 `CANDIDATE`。
- promotion 至少需要两个独立 evidence group，且来自不同发生日期；`RECOVERY_PATTERN` 与 `TRAINING_RESPONSE_PATTERN` 至少覆盖两次独立训练经历。
- confidence 由确定性 evidence count、独立性、时间跨度和一致性计算，不接受 Extractor 直接给最终置信度。
- `confidence < 0.70` 保持 `CANDIDATE`；达到 `0.70` 且不存在更高优先级冲突时才进入 `ACTIVE`。
- inferred confidence 上限为 `0.90`，不能伪装成用户明确事实。
- inferred 不能覆盖 active explicit Memory；冲突推断保持 candidate 或被拒绝。
- confidence 与 promotion 只按 distinct evidence groups 计算，不能按 Evidence row 数量计算。

只为置信度计算、证据独立性与冲突优先级编写少量 focused unit tests；不为 DTO、dataclass 或简单映射补机械测试。

## 7.3 Evidence independence

Phase 4 v1 使用确定性的 `evidence_group_key + independence_role` 表达独立证据组，不新增单独表：

```text
同一 Turn 的 Message + Turn
→ conversation:turn:<turn_id>

Workout + 该 Workout 的 Feedback
→ training:workout:<workout_id>

AthleteStateSnapshot
→ DERIVED_CONTEXT；不得单独增加 promotion group count

Completed Episode
→ episode:<episode_id>
```

`independence_role` 取 `PRIMARY | DERIVED_CONTEXT`。同一 Turn 中 user Message 为 PRIMARY、Turn 为同 group 的 DERIVED_CONTEXT；同一训练经历的 Workout / Feedback 共用一个 PRIMARY group；由这些 source 推导的 AthleteStateSnapshot 只能作为 DERIVED_CONTEXT。Completed Episode 仅在其底层 source groups 未同时作为该 Memory 的 PRIMARY 时可贡献一个 PRIMARY group，否则也是 DERIVED_CONTEXT。

`MemoryEvidence` 可以保留多条可追溯 source row，但 inferred confidence 与 promotion 只使用 `COUNT(DISTINCT evidence_group_key) WHERE independence_role = PRIMARY`。同一训练经历的 Workout、Feedback 与 derived Snapshot 不能包装成多份独立证明；同一 Turn 的 Message 与 Turn 也不能算两份。

---

# 8. Semantic Memory Lifecycle and Correction

状态：

```text
CANDIDATE → ACTIVE → SUPERSEDED
                   → EXPIRED
```

允许：

- explicit 通过验证后直接 `ACTIVE`。
- inferred 从 `CANDIDATE` 累积独立 Evidence 后晋升 `ACTIVE`。
- active 被更新、更明确或更晚的矛盾事实替代时成为 `SUPERSEDED`。
- `valid_until <= as_of` 的 active Memory 视为不可检索，并由 `MemoryLifecycleService.expire_due()` 转为 `EXPIRED`。
- activation / supersession / expiration transition 提交时分别写入 `activated_at` / `superseded_at` / `expired_at`。

禁止：

- `SUPERSEDED` / `EXPIRED` 回到 `ACTIVE`；需要新建或晋升新的 Memory。
- 物理覆盖旧内容、旧 Evidence 或旧有效期来伪造历史连续性。
- 两条相同用户、相同 `type + subject_key`、互相冲突的 active Memory。
- 原地修改 active Memory 的 `type`、`subject_key`、`value`、`origin`、`content`、`valid_from`、`valid_until` 或 confidence。Phase 4 v1 在 active 后冻结 confidence；实质语义、业务有效期或 provenance 变化必须创建新记录并 supersede 旧记录。

## 8.1 Deterministic supersession priority

对同一主题的新候选，按以下顺序处理：

1. 同 assertion 且 provenance class 相同：合并新的 Evidence；不新建逻辑 Memory。
2. 同 assertion 由 inferred 被后来 explicit confirmation 支持：旧 inferred → `SUPERSEDED`，新 explicit → `ACTIVE`，不得原地改写 origin。
3. 新 explicit correction 比旧 inferred 优先，旧 inferred → `SUPERSEDED`。
4. 新 explicit 比更早的旧 explicit 优先；precedence 依据 `source_occurred_at` / `valid_from`，不依据 Worker 执行顺序。
5. 新 inferred 不得 supersede active explicit。
6. 新 inferred 只有在证据更新、confidence 更高且通过冲突规则时才可 supersede 旧 inferred。
7. 如果旧事实晚于新候选，新候选作为历史 superseded 记录或被合并，不能反向覆盖较新的 active 认知。

supersede 新旧记录必须在同一短事务、同一用户行锁内完成，并写入 `superseded_by_id` 与 `superseded_at`。`source_occurred_at` 只决定事实 precedence；`superseded_at` 必须是 lifecycle transition 实际提交时间。Worker 延迟时不能把 Evidence 时间伪装成系统更早知道该纠正。

用户明确纠正：

```text
old inferred / explicit:
“更喜欢晚上训练”

later explicit user message:
“不是，我现在更喜欢早上跑。”
        ↓
old → SUPERSEDED
new explicit → ACTIVE
```

不能保留两个 active 结果让 Reasoner 自己猜。

---

# 9. Memory Evidence

正式模型：

```text
MemoryEvidence

id: UUID
user_id: UUID
memory_id: UUID

source_type: EvidenceSourceType
source_id: UUID
source_occurred_at: datetime
evidence_group_key: str
independence_role: PRIMARY | DERIVED_CONTEXT
role: SUPPORTS | CORRECTS | CONTRADICTS

created_at: datetime
```

`EvidenceSourceType` v1：

```text
MESSAGE
TURN
WORKOUT
WORKOUT_FEEDBACK
ATHLETE_STATE_SNAPSHOT
PLAN_CHANGE
EPISODE
```

Evidence 是 approved durable source 的多态引用。允许来源分为 Canonical Fact、Committed Conversation、Derived Domain State、Confirmed Domain Action 与 Completed Episode；它们都是正式持久化 source，但不都属于 Canonical Fact。数据库无法用单一 FK 覆盖所有表，因此 Application / Repository Boundary 必须在写入前验证：

- source 存在；
- source 属于同一 `user_id`；
- source 处于可作为正式证据的状态；
- Conversation source 来自 committed Turn；
- `source_occurred_at` 来自 durable source，不使用 projector 执行时间替代；
- 同一 Memory 不重复关联同一 source。
- `evidence_group_key` 与 `independence_role` 按 §7.3 确定性生成，不能由 Extractor 自由提供。

唯一约束：

```text
UNIQUE(memory_id, source_type, source_id, role)
```

Evidence Detail 不进入默认 Context。它用于审计、解释、重放和以后可能的正式查询 Tool。

---

# 10. Episode Model

`Episode` 回答：

> **以前发生过什么具有未来决策价值的重要经历？**

正式模型：

```text
Episode

id: UUID
user_id: UUID
type: EpisodeType
summary: str

started_at: datetime
ended_at: datetime
completed_at: datetime | None
superseded_at: datetime | None
importance: float
status: BUILDING | COMPLETED | SUPERSEDED

projector_name: str
projector_version: str
embedding_model: str
embedding_version: str
embedding: vector

logical_key: str
superseded_by_id: UUID | None
created_at: datetime
updated_at: datetime
```

Phase 4 v1 精确支持：

```text
FATIGUE_AND_RECOVERY
PLAN_ADAPTATION_OUTCOME
```

- `FATIGUE_AND_RECOVERY`：负荷 / 质量下降 / 主观疲劳 / Athlete State 风险出现，随后降负荷或恢复，形成有结局的时间段。
- `PLAN_ADAPTATION_OUTCOME`：确认的 PlanChange 及其后续训练 / 状态证据表明调整有效、无效或仍未知。

Phase 4 不自动识别 race preparation、goal transition 或任意“有趣经历”。无充分后续结果的 Episode 保持 `BUILDING`，默认 Retrieval 只返回 `COMPLETED`。

`ended_at` 表示现实经历何时结束；`completed_at` 表示 Run Coach 何时正式把 Episode 认定为 completed。`logical_key` 是跨 projector version 稳定的现实 Episode identity，例如 `plan_change:<plan_change_id>` 或 `fatigue_trigger:<trigger_snapshot_id>`。

`summary` 是领域压缩叙述，不复制原始对象；必须包含主要时间范围、触发、干预和结果，不得声称 Evidence 中不存在的因果确定性。

## 10.1 EpisodeEvidence

```text
EpisodeEvidence

id: UUID
user_id: UUID
episode_id: UUID
source_type: EvidenceSourceType
source_id: UUID
source_occurred_at: datetime
role: TRIGGER | CONTEXT | INTERVENTION | OUTCOME
created_at: datetime
```

唯一约束：

```text
UNIQUE(episode_id, source_type, source_id, role)
```

完整 Episode 至少拥有一个 `TRIGGER` 和一个 `OUTCOME` Evidence；Plan Adaptation Episode 还必须拥有 `INTERVENTION` PlanChange Evidence。所有 evidence 必须属于同一用户并落在可解释的时间范围内。

`MemoryEvidence` 可以引用 `COMPLETED Episode`；`EpisodeEvidence` v1 明确不允许 `source_type = EPISODE`，避免 Episode composition、递归依赖与循环。以后如有组合 Episode 需求必须另行扩展 Contract。

---

# 11. Projection Flow

Projection 与 Agent Runtime Reasoning 分离：

```text
Canonical Facts / Committed Conversation
        ↓
Projection Application Service
        ↓
Extractor / Detector Port
        ↓
Structured Candidate
        ↓
Evidence Ownership Validation
        ↓
Domain Validation / Merge / Supersede
        ↓
Embedding Provider
        ↓
Short Persistence Transaction
        ↓
Candidate / Active Memory or Building / Completed Episode
```

LLM / embedding 调用不得位于数据库事务或用户行锁内。

## 11.1 Conversation projection v1

```text
TurnCommitted
        ↓
SemanticMemoryProjectionService.project_committed_turn(
    user_id,
    turn_id,
    projector_version
)
        ↓
ConversationReader.get_committed_turn_messages(user_id, turn_id)
        ↓
exactly one canonical user message + committed assistant message
        ↓
SemanticMemoryExtractor
        ↓
structured candidate(s)
        ↓
Domain merge transaction
```

Projector 必须再次查询 canonical Turn 状态，不能只信任进程内 event payload。`TurnCommitted` 中的 message ids 可用于一致性校验，但内容从 canonical repository 读取。

Extractor 是正式 Port：

```text
SemanticMemoryExtractor.extract(
    user_message,
    assistant_message,
    committed_at,
    supported_types,
) -> tuple[SemanticMemoryCandidate, ...]
```

Extractor prompt 使用中文，输出严格结构化数据，不共享 Agent Reasoner、PromptRenderer 或 ReasoningState。模型响应必须通过 schema 与 Domain Validation；空候选是合法成功结果。

## 11.2 Inferred projection v1

`SemanticMemoryProjectionService.project_evidence_set()` 接收明确的 canonical source ids，读取并验证 Evidence，产生 / 更新 inferred candidate。Phase 4 可以由维护命令或场景编排显式调用；Phase 5 再由 durable events 自动触发。

不得让一次 Turn 的 assistant 推测直接调用此入口并形成 active inferred Memory。

## 11.3 Episode projection v1

```text
EpisodeProjectionService.project_window(
    user_id,
    type,
    started_at,
    ended_at,
    source_ids
)
```

服务读取 Workout、Feedback、AthleteStateSnapshot、PlanChange 等 approved durable evidence，由有限 Episode Detector 产生结构化 EpisodeCandidate，再进行 Evidence 与状态验证。Phase 4 不要求后台自动扫描所有历史。

---

# 12. Extraction Safety

Extractor / Detector 必须遵守：

- 不因一次随口表达、当天安排或临时情绪生成永久 Memory。
- 不把 assistant 建议、复述、猜测或模型自我陈述标成用户 explicit fact。
- 不把推测写成 explicit。
- 不覆盖 Canonical Facts，不把计划、训练、反馈或 Athlete State 内容复制成 Memory。
- 不生成医疗诊断 Memory；身体风险信息仍由 canonical Feedback / Athlete State 与 Safety Rule 处理。
- 不读取或存储 Chain of Thought。
- 不从 failed / cancelled / uncommitted Turn 提取。
- 不接受 unsupported type、无 primary Evidence、越界时间或无界 content。
- 对证据不足返回空候选或 candidate，不伪造 active 结果。

未知 extractor / embedding 错误必须失败并保留可重放性，不能写空成功 receipt 掩盖失败。

---

# 13. Projection Idempotency and Versioning

新增 `memory_projection_runs`：

```text
MemoryProjectionRun

id: UUID
user_id: UUID
projector_name: str
projector_version: str
projection_key: str
input_fingerprint: str
input_checkpoint: bounded JSONB
status: COMPLETED | FAILED
result_summary: JSONB
error_code: str | None
started_at: datetime
completed_at: datetime | None
```

唯一约束：

```text
UNIQUE(user_id, projector_name, projector_version, projection_key)
```

规则：

- Extractor / embedding 可以在事务外执行；最终 run receipt、Memory / Episode、Evidence 和 supersession 在一个短事务中提交。
- 同一 projection key + projector version + input fingerprint 并发执行时，在用户行锁下检查 receipt；三者相同且已 `COMPLETED` 才直接返回相同逻辑结果。`input_checkpoint` 保存用于 fingerprint 的规范化 source identities / versions，不保存原始 Evidence payload。
- “合法但没有候选”也记录 completed receipt，避免重复调用不确定 extractor。
- 失败不得记录 completed；可使用同一 identity 重试。
- `projection_key` 是投影幂等身份：conversation 使用 `turn:<turn_id>`；inferred 使用 `inferred:<type>:<canonical sorted evidence identity hash>`；Episode 使用类型特定稳定 anchor，不 hash 会随 outcome 增长而变化的完整 Evidence set。
- `PLAN_ADAPTATION_OUTCOME` 使用 `plan_change:<plan_change_id>`；`FATIGUE_AND_RECOVERY` 使用 `fatigue_trigger:<trigger_snapshot_id>`，保证 BUILDING → COMPLETED 仍是同一 Episode。`input_fingerprint` 由本次实际可见的规范化 source identities + source versions / lifecycle timestamps 计算：相同输入重放跳过；新增 OUTCOME 导致 fingerprint 变化，允许重新评估并完成同一 Episode。较旧 checkpoint 在较新 superset checkpoint 完成后到达时返回 obsolete no-op，不得把 receipt 或 Episode 回退；无法比较的并发输入必须在用户锁内重读当前 durable evidence，形成统一最新 checkpoint。
- 业务去重独立依赖 Memory slot / assertion identity、Evidence uniqueness 与 Episode logical identity，防止不同 projection 形成重复逻辑结果。
- `projector_version` 改变允许产生新的 ProjectionRun，但输出仍必须经过既有 Memory / Episode identity、merge、conflict 与 lifecycle 规则；版本升级绝不能绕过 active uniqueness。版本迁移策略必须由维护命令指定。
- `embedding_version` 与 `projector_version` 分离，允许只重建 embedding。

Phase 5 的 consumer idempotency 不能替代本节的业务幂等；Worker 在 service commit 后崩溃时，服务自身仍必须安全重放。

---

# 14. Embedding and Search Decision

Phase 4 v1 选择：

```text
PostgreSQL 16
+ pgvector
+ metadata filter
+ vector similarity
+ deterministic rerank
```

不引入 Pinecone、Milvus、Elasticsearch 或独立 Vector Database。Memory 与 Evidence 的 source of truth 仍是 PostgreSQL；pgvector 只提供同库检索能力。

正式 Port：

```text
EmbeddingProvider.embed(texts: tuple[str, ...]) -> EmbeddingBatch
```

`EmbeddingBatch` 至少返回 provider-neutral vectors、model、version 与 dimensions。Domain Model 不依赖 OpenAI SDK 类型。Phase 4 基线维度固定为 `1536`，启动时 provider 维度不匹配必须 fail fast；模型名称通过配置注入，不写入 Domain。

每条 SemanticMemory / Episode 保存用于检索的 embedding metadata。embedding 失败时不创建 active 可检索结果，也不静默使用随机 / 零向量 fallback。

---

# 15. Retrieval

Semantic 与 Episodic Retrieval 分开：

```text
MemoryRetrievalService.retrieve(
    user_id,
    query,
    as_of,
    semantic_limit=8,
    episode_limit=4
) -> MemoryRetrievalResult
```

## 15.1 Candidate filtering

Semantic：

- `user_id` 精确过滤；
- `activated_at IS NOT NULL AND activated_at <= as_of`；
- `superseded_at IS NULL OR superseded_at > as_of`；
- `expired_at IS NULL OR expired_at > as_of`；
- `valid_from <= as_of`；
- `valid_until IS NULL OR valid_until > as_of`。

Episode：

- `user_id` 精确过滤；
- `completed_at IS NOT NULL AND completed_at <= as_of`；
- `superseded_at IS NULL OR superseded_at > as_of`；
- `ended_at <= as_of`。

Retrieval 使用 knowledge interval + business validity interval 重建 `as_of` 时系统当时可用的认知，不能只看记录当前 `status`。因此今天已 superseded 的 Memory 在其历史 knowledge interval 内仍可被历史查询命中；一个现实上已结束但当时尚未完成投影的 Episode 不能泄漏到更早 Context。即使 lifecycle maintenance 尚未把超期 active 行更新为 expired，业务有效期也必须阻止当前检索。

## 15.2 Hybrid ranking v1

先按 metadata 过滤，再分别取最多 24 条 Semantic 候选与 12 条 Episode 候选进行确定性 rerank。以下数字是 `RetrievalPolicy phase4.v1` 的初始默认参数，不是 Architecture invariant：

```text
semantic_score =
    0.60 * cosine_similarity
  + 0.20 * confidence
  + 0.10 * recency_score
  + 0.10 * explicit_origin_boost

episode_score =
    0.65 * cosine_similarity
  + 0.20 * importance
  + 0.15 * recency_score
```

所有分量归一化到 `[0, 1]`，相同 score 依次按 `valid_from/ended_at DESC, id ASC` 打破平局。user filter、双时间 eligibility、bounded candidate set、bounded context、deterministic tie-break 与 policy version 是 Contract；Phase 6 Eval 可以在保持这些不变量和相同版本可复现性的前提下调整权重。参数不能在 repository 中散落。

## 15.3 Context budget

- Semantic 最多 8 条，序列化文本合计最多 1,600 Unicode 字符。
- Episode 最多 4 条，序列化文本合计最多 2,000 Unicode 字符。
- 单条 Memory content 最多 240 字符；单条 Episode summary 最多 500 字符。
- 超出预算按排名从尾部丢弃，并在内部 retrieval result 标记 `truncated`；不截断成语义残片。

这些是硬上限，不因数据库中条目增多而扩大 Prompt。

---

# 16. Context Integration

Phase 4 扩展但不重构现有 View：

```text
MemoryView

id
type
content
origin
confidence
valid_from
valid_until
```

```text
EpisodeView

id
type
summary
started_at
ended_at
importance
```

不加入：

- embedding；
- Evidence graph；
- projector internal state；
- full canonical source objects。

真实 `MemoryContextProvider` 使用 `current_input` 作为 query，并使用可信 clock 作为 `as_of`，调用 Retrieval Service 后映射为现有 `ContextBundle` 两个字段。`ContextAssembler` 方法签名、AgentRuntime 主循环与 Tool Runtime 不发生结构性变化。

`PromptRenderer` 只需呈现 explicit / inferred 区别、Memory 有效期和 Episode 时间范围；不得把 Memory 描述成 canonical fact，也不得重复 `current_input`。Prompt contract 必须明确：当前 explicit user input 高于冲突 Memory，更新的 canonical WorkingContext 高于冲突 Memory；Projection 尚未提交不能导致旧 Memory 覆盖本轮纠正。

---

# 17. Memory Tool Decision

Phase 4 不新增任何 Memory Tool。

- 默认最相关的少量 Memory 由 `MemoryContextProvider` 注入。
- Agent 不能通过 `write_memory` 绕过 Projection Pipeline。
- v1 没有足够产品证据需要深挖完整 Evidence Graph，因此不实现 `search_memory`。
- 后续如果 Eval 证明默认 Context 不足，可以另行增加 read-only `search_memory` Tool；它必须走 Tool Runtime、受 user scope 与结果预算保护，且仍不能写 Memory。

---

# 18. Persistence

Migration：

```text
0004_phase4_long_term_memory.py
```

启用：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

新增表：

```text
semantic_memories
memory_evidence
episodes
episode_evidence
memory_projection_runs
```

关键约束 / 索引：

```text
semantic_memories:
  PK(id)
  FK(user_id -> users.id)
  CHECK(confidence between 0 and 1)
  CHECK(valid_until is null or valid_until > valid_from)
  INDEX(user_id, status, type, valid_from desc)
  INDEX(user_id, activated_at, superseded_at, expired_at)
  INDEX(user_id, type, subject_key, status)
  UNIQUE(user_id, type, subject_key) WHERE status = active
  UNIQUE(user_id, assertion_hash) WHERE status in candidate/active
  vector HNSW index using cosine distance

memory_evidence:
  FK(memory_id -> semantic_memories.id)
  INDEX(user_id, source_type, source_id)
  UNIQUE(memory_id, source_type, source_id, role)

episodes:
  FK(user_id -> users.id)
  CHECK(ended_at >= started_at)
  CHECK(importance between 0 and 1)
  UNIQUE(user_id, type, logical_key)
  INDEX(user_id, status, type, ended_at desc)
  INDEX(user_id, completed_at, superseded_at, ended_at)
  vector HNSW index using cosine distance

episode_evidence:
  FK(episode_id -> episodes.id)
  INDEX(user_id, source_type, source_id)
  UNIQUE(episode_id, source_type, source_id, role)

memory_projection_runs:
  UNIQUE(user_id, projector_name, projector_version, projection_key)
  input_fingerprint / input_checkpoint update only when a newer input revision completes
  INDEX(status, started_at)
```

`projector_version` 只存在于 Projection provenance / identity，不参与 SemanticMemory active slot uniqueness 或 Episode logical identity。PostgreSQL partial unique constraint 与同一用户行锁下的 merge transaction 共同保证 active Memory 不并存；仅靠“先查后插”不满足并发安全。

---

# 19. Security and User Isolation

- user identity 只来自可信 `RequestContext`、Lifecycle Event 或 Worker Task trusted envelope；Extractor 输出不包含可控制的 `user_id`。
- 所有 repository 方法均以 `user_id + object identity` 查询。
- 关联 Evidence 时必须再次验证 source owner；不能只验证 Memory owner。
- 跨用户 source id 返回 not found 语义，不泄漏对象存在性。
- pgvector 查询必须在距离排序前应用 `user_id` 与 status 过滤；禁止全局 Top-K 后在应用层过滤用户。
- 日志不记录完整私密 message、Memory content、embedding 或 Evidence payload。
- Memory 不保存密钥、认证信息、医疗诊断或隐藏推理。

---

# 20. Failure Semantics

- invalid extractor output：本次 projection 失败，不写部分 Memory。
- Evidence 缺失、未 committed 或跨用户：permanent domain failure，fail fast。
- LLM / embedding timeout：transient infrastructure failure，Phase 4 记录安全日志并允许相同 source identity 手动重放。
- persistence conflict：在用户锁内重新读取并按 merge 规则处理；不能无条件 retry last-write-wins。
- listener failure 不影响已提交 ChatResult，但必须可观测且不得写伪造成功 receipt。
- Episode evidence 不足：合法地保持 `BUILDING` 或不创建；不得伪造 outcome。
- query embedding、pgvector 或 Memory repository retrieval failure：抛出 typed `MemoryRetrievalInfrastructureError`，使 Context Assembly / Agent Run 安全失败；Phase 4 v1 禁止静默返回 `[]` 退化成 Null Provider。

Phase 4 明确认可 post-commit crash window 是 current limitation；Phase 5 用 Outbox + durable queue 修复。

---

# 21. Migration, Fixtures, Seed, Rollback

## Migration

- 部署前 PostgreSQL 镜像 / 实例必须支持 pgvector；extension 缺失时 migration fail fast。
- Migration 只新增 Memory 表，不改写 Phase 1–3 canonical rows。
- 不为历史 Conversation 自动生成 Memory；历史回放必须是显式、版本化、可审计的维护动作。

## Fixtures and seed

- 现有 Phase 1–3 fixtures 保持兼容，Memory 表为空时真实 Provider 返回空集合。
- Phase 4 vertical-slice fixture 通过 Projection Application Service 创建 Memory / Episode，不直接插入绕过 Evidence Validation 的“魔法行”。
- 不为了旧测试保留 Null Provider 生产 wiring。

## Rollback

- 应用回滚前停止新的 Phase 4 projection。
- downgrade 可以删除 Phase 4 新表；默认不删除共享 `vector` extension。
- 回滚会丢失新 Memory 数据，执行前必须备份；Canonical Facts、Conversation 与 Athlete State 不受影响。

---

# 22. Acceptance Strategy

测试是 Architecture 与 Phase Contract 的支持证据，不是规格来源。Phase 4 只新增七个高价值 acceptance scenarios；不按 class / method / repository / serialization path 展开测试矩阵。

主接缝优先使用真实 PostgreSQL、真实 Application Service、`ChatService` / Lifecycle、ContextAssembler 和 deterministic fake extractor / embedding adapter。只有外部模型协议边界使用 fake provider；不得用大量 mock 证明持久化、隔离或幂等。

## Scenario 1 — Explicit memory vertical slice

用户提交：

```text
“以后周三晚上不要给我排训练，我有课。”
```

断言 committed Turn 产生一个 active `AVAILABILITY_CONSTRAINT`，primary Evidence 指向 canonical user Message；新 Thread 中“帮我看看下周怎么安排”能够把该 Memory 注入 Context，且 `current_input` 仍恰好出现一次。

## Scenario 2 — Correction and supersession

已有“更喜欢晚上训练”的 active inferred Memory，用户后来明确确认相同 assertion，再进一步纠正为“现在更喜欢早上跑”。断言 correction Turn 推理期间以 current explicit input 为准，不能被尚未 supersede 的旧 Memory 覆盖；inferred → explicit confirmation 通过新 revision 保留 provenance，纠正后旧记录保留 Evidence 但被 supersede，新 explicit Memory 唯一 active；当前检索不返回旧结果，而以纠正提交前的历史 `as_of` 仍能重建当时 active 的旧认知。

## Scenario 3 — Unsuccessful turns cannot become memory

分别驱动一个 failed Turn 和一个 cancelled Turn，其中 user message 看似包含长期偏好。断言没有 projection receipt、Memory 或 Evidence；只验证这一个终态不变量，不复制 Phase 1–3 的全部失败测试。

## Scenario 4 — Projection idempotency and inferred promotion

同一 `TurnCommitted` 以 `turn:<turn_id>` projection key 重放并并发投递，只产生一个逻辑 Memory 与一组唯一 Evidence。另用两个独立训练经历投影同一 inferred recovery pattern：Workout + Feedback + derived Snapshot 的重叠 source 只算一个 evidence group；第二个独立经历到达并满足阈值后只晋升一个 active result，confidence 不超过 inferred 上限。Episode stable anchor 在加入 outcome 后仍命中同一 BUILDING record。

## Scenario 5 — Retrieval relevance and bounded context

同一用户拥有跨业务有效期和 knowledge lifecycle 的 active、superseded、expired 与低相关 Memory / Episodes。当前与历史 `as_of` 查询分别按双时间 eligibility 返回当时系统已知且业务有效的结果；当时尚未 completed 的 Episode 不提前泄漏。结果按 versioned default policy 稳定排序，Semantic / Episode 数量与字符预算均不超限。

## Scenario 6 — Episode creation and later retrieval

历史 high fatigue + failed quality evidence + confirmed load reduction + later recovery 形成 completed `FATIGUE_AND_RECOVERY` Episode；Episode 包含 trigger/intervention/outcome evidence。以后出现相似问题时该 Episode 被检索进入 Context，而 canonical Workout / Snapshot / PlanChange 未被复制到 Episode 表。

## Scenario 7 — Cross-user isolation vertical slice

User A 与 User B 使用相似文本、相同 Memory type 和相近向量。断言 projection、Evidence association、supersession、vector retrieval 与 Context injection 始终 user-scoped；User B 不能通过猜测 A 的 source id 建立 Evidence。

## Focused tests only

仅在存在真实确定性边界时增加少量 focused tests：

- type-specific assertion normalization / hash；
- explicit-over-inferred 与 event-time supersession precedence；
- 双时间 temporal eligibility、稳定 tie-break 与预算选择。

不要求为 dataclass、DTO mapping、薄 Repository wrapper、基础 serialization、dependency wiring 或 getter 编写单元测试。

现有 Phase 1–3 regression suite 必须继续通过。只在 Phase 4 引入了现实回归风险的地方复用 / 扩展既有场景，例如 current input exactly once、committed-only conversation 与 user isolation；不复制整套旧测试。

---

# 23. Implementation Order

1. **Baseline and contract review**：运行现有 tests / lint，确认 `ARCHITECTURE.md`、Phase 1–3 与当前接缝。
2. **Domain model**：实现有限枚举、SemanticMemory、Episode、Evidence、candidate 与生命周期规则。
3. **Migration and PostgreSQL capability**：启用 pgvector，创建五张表、约束和索引。
4. **Repository / Evidence Reader ports**：实现 user-scoped persistence、source ownership validation 与 committed Turn reader。
5. **Projection idempotency**：先实现 projection key、Memory / assertion / Episode identity、用户锁下 merge / supersede，再接模型。
6. **Extraction and embedding boundaries**：实现正式 Ports、结构化 adapter、版本与失败语义；外部调用保持在事务外。
7. **Semantic projection**：实现 explicit、inferred candidate / promotion 与 TurnCommitted best-effort listener。
8. **Episode projection**：只实现两个 v1 Episode types 与 Evidence completeness。
9. **Retrieval**：实现 metadata + vector + deterministic rerank、状态 / 时间过滤与预算。
10. **Context integration**：扩展精简 View，替换生产 Null Provider，不改 ContextAssembler / AgentRuntime API。
11. **Acceptance evidence**：实现七个场景和必要的 focused tests，运行全部 Phase 1–3 regression。
12. **Independent review**：由未实现该 Phase 的 reviewer 对照 Architecture、Phase Contract 与实际代码审查。

不得先从 Tool、Prompt 技巧或 Worker 开始，也不得让测试反向定义 Domain Model。

---

# 24. Definition of Done

Phase 4 完成必须同时满足：

- [ ] 实现符合 `ARCHITECTURE.md` 的 Canonical Fact / State / Memory 边界。
- [ ] Semantic explicit / inferred、有限类型、candidate / active / superseded / expired 与纠正规则均按本 Contract 实现。
- [ ] 每条 Memory / Episode 有同用户、可验证、正式状态的 Evidence。
- [ ] Projection 与 Retrieval 分离；AgentRuntime、ContextAssembler 与 ToolExecutor 不写 Memory。
- [ ] 相同 projection key / projector version / input fingerprint 的重复或并发执行只产生一个逻辑结果；新 input fingerprint 可以推进同一 Episode，projector 升级不能绕过业务 identity。
- [ ] Memory / Episode 的 knowledge time 与 business time 分离，历史 `as_of` 不泄漏未来认知也不丢失当时认知。
- [ ] PostgreSQL + pgvector 是唯一长期 Memory store；无独立 Vector DB。
- [ ] 真实 MemoryContextProvider 已成为正式 wiring，Null Provider 不再是生产路径。
- [ ] Context 有确定上限，不注入 Evidence Graph，不重复 current input。
- [ ] 七个 critical acceptance scenarios 通过，必要的真实 PostgreSQL integration evidence 成立。
- [ ] 现有 Phase 1–3 regression suite 继续通过。
- [ ] 实现说明记录 migration、projector / embedding version、已知 Phase 4 delivery limitation 与重放方式。
- [ ] 独立 code / design review 对照 Architecture、Phase Contract 与实际代码后，没有 unresolved blocker。

“实现 Agent 自己编写的所有测试通过”不能单独证明 Phase 完成。

---

# 25. Final Acceptance Scenarios

## Semantic vertical slice

```text
User:
“以后周三晚上不要给我排训练，我有课。”
        ↓
Transaction B commits canonical conversation
        ↓
TurnCommitted
        ↓
SemanticMemoryProjectionService
        ↓
ACTIVE EXPLICIT availability constraint
+ Message / Turn Evidence
        ↓
New Thread:
“帮我看看下周怎么安排。”
        ↓
MemoryContextProvider retrieves relevant Memory
        ↓
ContextBundle.semantic_memories
        ↓
Agent receives the constraint without duplicating current input
```

## Episode vertical slice

```text
Historical training-load rise
+ failed quality session
+ fatigue Feedback
+ HIGH AthleteStateSnapshot
+ confirmed PlanChange reducing load
+ later recovery Snapshot
        ↓
EpisodeProjectionService
        ↓
COMPLETED FATIGUE_AND_RECOVERY Episode
+ trigger / intervention / outcome Evidence
        ↓
Later similar training question
        ↓
Episode Retrieval
        ↓
ContextBundle.episodic_memories
```

两条链真实成立且没有复制 Canonical Facts、没有 Runtime 直接写 Memory 后，Phase 4 才具备交付资格。

---

# 26. Phase 4 → Phase 5 Contract

Phase 4 留给 Phase 5 的稳定接口：

```text
SemanticMemoryProjectionService.project_committed_turn(...)
SemanticMemoryProjectionService.project_evidence_set(...)
EpisodeProjectionService.project_window(...)
MemoryRetrievalService.retrieve(...)
```

这些服务已经具备业务幂等、Evidence、版本和并发 merge 语义。Phase 5 只改变“谁、何时、如何可靠地调用”，不得重新设计 Memory Domain。

Phase 4 明确保留的临时限制：

```text
DB COMMIT
↓
process crash / listener failure
↓
projection may be delayed until manual replay
```

Phase 5 必须用 durable business event、Transactional Outbox、Queue、Worker、retry 和 idempotent consumer 消除此缺口，并移除生产 in-process projection owner。
