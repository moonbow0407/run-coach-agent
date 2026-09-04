# Phase 6 — Agent Evaluation MVP

> **Status:** Draft — Implementation Contract
> **Depends on:** `docs/ARCHITECTURE.md`, Phase 1–5
> **Scope:** Scenario-driven Agent Eval + Context Trace + Deterministic Graders + CLI/JSON Report

---

# 1. Phase Goal

Phase 6 回答：

> **当 Prompt、Tool、Memory、Coaching 逻辑或模型发生变化时，Run Coach 如何以可重复、可定位的方式发现 Agent 行为退化？**

本 Phase 的首要目标是开发回归，而不是模型排行榜或在线质量平台。

目标链路：

```text
YAML Eval Case
      ↓ strict validation
Fixture Registry
      ↓
Eval Runner
      ├── Real ChatService + Real LLM
      ├── Memory Retrieval Service
      └── Deterministic Worker Drain
      ↓
Context RunStep + Tool Trace + Domain State
      ↓
Deterministic Graders
      ↓
CLI Report + JSON Artifact + Baseline Diff
```

MVP 必须能够区分：

```text
Agent Behavior Failure
Infrastructure / Environment Error
Multi-trial Instability
```

并在失败时回答：

```text
模型看到了什么 Context
发现和调用了哪些 Tool
Tool 是否真正执行成功
Memory 是否被召回并注入
最终产生了什么 Domain State
```

---

# 2. Current Implementation Findings

当前代码已经具备 Eval Harness 的主要生产接缝：

- `ChatService` 是一轮真实用户交互的 Application Orchestrator，负责 Thread、Turn、Message 与 AgentRun 生命周期。
- `AgentRuntime` 已形成 Context → Reason → Tool → Observation → Final 循环。
- 每个 AgentRun 拥有独立 `ToolSession`，动态 Tool Discovery 不跨 Run 泄漏。
- `RunStep` 已持久化 reasoning、tool_call、observation、final，可重建 Tool 轨迹。
- `MemoryRetrievalService` 已实现 Semantic / Episodic Memory 的过滤、重排与预算裁剪。
- Phase 5 已通过 Outbox、Publisher、Consumer 与 Handler 持续驱动 Memory Projection、Athlete State 和 PlanChange 收尾。
- 现有 `ScriptedReasoner` 场景测试能够验证 Runtime 合同，但不能回答真实模型是否会作出正确行为选择。

进入 Eval MVP 前仍缺少三个正式能力：

1. RunStep 没有记录本轮真正注入模型的 Context Manifest。
2. Agent Trace 只有写端口，没有供 Eval 使用的正式只读端口。
3. 尚无 Case Schema、Fixture Registry、Runner、Grader、Report 与 CLI。

---

# 3. Goals

Phase 6 必须实现：

- 15 个固定场景，覆盖 Tool、Memory、Coaching 三类行为。
- Tool / Coaching Case 使用真实 `ChatService + AgentRuntime + LLMReasoner`。
- Memory Case 根据评测目标使用 Retrieval Service、确定性 Projection 或 ChatService，不强行混成一条链。
- 使用生产 RunStep、真实 Context 结果和真实 Domain State 评分。
- Grader 全部 deterministic；自由文本回答只展示，不参与自动分。
- 默认单 Trial，支持显式 `--trials 3` 建立稳定基线。
- CLI 输出人类可读报告，同时保存可比较的 JSON artifact。
- 支持通过 `--baseline` 比较两次运行的新增失败、恢复和指标变化。
- 使用独立 Eval PostgreSQL 数据库，并在任何清理前执行严格防误连校验。
- pytest 验证 Eval Harness 自身；真实 LLM Eval 由开发者手动运行。

---

# 4. Non-Goals

Phase 6 不实现：

- Web Dashboard、在线 Eval 服务、Eval 数据库表或历史查询 API。
- 自动 Prompt 优化、多模型排行榜、100+ Tool 压测。
- 用户 Simulator、几十轮长对话或自动生成 Case。
- 通用 LLM-as-a-Judge 平台。
- 自由文本风格、帮助程度、措辞自然度或完整事实一致性的自动评分。
- Memory Extraction 质量评测；Memory Conflict Case 使用确定性 Extractor 隔离 Lifecycle。
- Redis / ARQ 可靠性重复验收；该能力继续由 Phase 5 integration scenarios 负责。
- 每个 Case 覆盖或放宽生产 `agent_max_steps`。
- 在 CI 中把真实 LLM Pass Rate 作为 PR 强门禁。
- 为 Eval 创建第二套 Agent Runtime、Tool Trace、Memory 或 Coaching 业务实现。

---

# 5. Architecture Invariants

1. Eval 代码属于正式后端模块，必须放在 `backend/app/evals`，不能放在包外的 `backend/evals`。
2. Tool / Coaching 的真实 Agent Case 必须从 `ChatService` 进入，不直接调用 Reasoner。
3. Memory Retrieval 是独立质量边界，可以直接调用正式 Retrieval Service；不得为了入口统一引入无关 Reasoner 噪音。
4. Eval 消费生产 Trace 和 Domain State，不创建第二套 `EvalStep`、`EvalToolCall` 或 `EvalObservation`。
5. Context Trace 只记录 ID、版本与裁剪元数据，不持久化完整 Prompt、Memory 正文或隐藏推理。
6. Tool Grader 必须区分“尝试调用”和“执行成功”；禁止工具只要被模型尝试即为行为失败。
7. Dynamic Discovery 成功必须同时证明 search 命中和目标 Tool 后续执行成功。
8. Memory Conflict 查询必须使用新 Thread，防止 recent conversation 替 Memory 答对。
9. Domain Outcome 必须关联当前 Case 的 `turn_id / run_id`，不能只按用户读取任意最新对象。
10. Phase 5 异步结果必须在 Grading 前经过显式 consistency barrier；未完成属于 ERROR，不属于行为 FAIL。
11. 每个 Case / Trial 使用独立用户；同一 Trial 的多轮对话显式传递 thread_id。
12. Case 只允许合成数据，不允许使用真实用户训练或聊天数据。
13. Eval 数据库清理只能作用于经过严格验证的独立 Eval 数据库。
14. Eval Case、Result、JSON Artifact 都必须有严格 schema version，未知字段和未知版本 fail fast。
15. Phase 1–5 regression suite 必须继续通过。

---

# 6. Module Boundary

目录结构：

```text
backend/
├── app/
│   ├── evals/
│   │   ├── cases/
│   │   │   ├── tool.yaml
│   │   │   ├── memory.yaml
│   │   │   └── coaching.yaml
│   │   ├── fixtures/
│   │   ├── graders/
│   │   ├── models.py
│   │   ├── loader.py
│   │   ├── environment.py
│   │   ├── runner.py
│   │   ├── trace.py
│   │   ├── report.py
│   │   └── cli.py
│   ├── agent/
│   ├── memory/
│   ├── coaching/
│   └── infrastructure/
│       └── evals/
│           └── readers.py
└── .eval-results/
```

职责：

- `app.evals`：Case 合同、执行编排、评分与报告。
- `app.agent`：生产 Context / RunStep 与 Trace Reader Port。
- `app.memory`：生产 Memory Retrieval / Projection 语义。
- `app.coaching`：生产 PlanChange / Plan / Athlete State 语义。
- `app.infrastructure.evals`：Eval 所需的只读 Domain State Adapter，不在 Eval Core 中直接访问 ORM。

`.eval-results` 必须加入 `.gitignore`。YAML Case 必须通过 package-data 配置进入安装包。

---

# 7. Evaluation Levels

MVP 不要求所有 Case 使用同一个入口，而是按被评价能力选择最小真实边界。

## 7.1 Real Agent

用于：

```text
Tool Selection
Tool Discovery
Tool Governance
Coaching Decision
```

执行：

```text
Fixture
  ↓
ChatService
  ↓
AgentRuntime + Real LLMReasoner
  ↓
RunStep + Domain State
```

## 7.2 Memory Retrieval

用于 Semantic / Episodic Recall：

```text
Seed canonical Memory + Evidence + real embedding
  ↓
MemoryRetrievalService.retrieve
  ↓
selected Memory IDs + truncation metadata
```

该层不调用 Reasoner，避免把 Retrieval Failure 与模型行为混在一起。

## 7.3 Memory Lifecycle

用于显式纠正与 supersession：

```text
Committed Turn + deterministic Extractor
  ↓
Outbox / in-process Worker Drain
  ↓
Semantic Memory Lifecycle
  ↓
new-thread Retrieval
```

Reasoner 使用 `ScriptedReasoner`，因为本 Case 不评价模型回复或 Extraction。

## 7.4 Context Injection

用于验证实际送入 Reasoner 的 Context：

```text
Seed retrievable Memory
  ↓
ChatService + AgentRuntime
  ↓
CONTEXT RunStep
  ↓
assert selected Memory ID was injected
```

本 Case 可以使用 `ScriptedReasoner`，因为评分目标发生在 Reasoner 调用之前。

---

# 8. Context RunStep

## 8.1 New RunStep Kind

新增：

```python
class RunStepKind(StrEnum):
    CONTEXT = "context"
```

AgentRuntime 在 `ContextAssembler.assemble()` 成功之后、第一次 reasoning 之前调用：

```python
await trace_recorder.record_context(
    run_id=command.run_id,
    manifest=ContextManifest(...),
)
```

完整成功轨迹从：

```text
reasoning → ... → final
```

变为：

```text
context → reasoning → ... → final
```

## 8.2 Context Manifest

持久化字段：

```text
goal_id
plan_id
plan_version
athlete_state_version
athlete_state_as_of
semantic_memory_ids
episodic_memory_ids
memory_policy_version
semantic_truncated
episodic_truncated
```

明确禁止：

```text
完整 system prompt
完整 conversation history
Memory content
Embedding
JWT / API key
隐藏 chain of thought
```

## 8.3 Memory Context Result

当前 MemoryContextProvider 只返回两个列表，无法把 policy 与 truncation 传给 Trace。Phase 6 将其收紧为结构化结果：

```python
@dataclass(frozen=True)
class MemoryContextResult:
    semantic: tuple[MemoryView, ...]
    episodic: tuple[EpisodeView, ...]
    policy_version: str
    semantic_truncated: bool
    episodic_truncated: bool
```

`ContextBundle` 继续携带 Prompt 所需的 Memory View，同时携带上述检索元数据供 Context Manifest 使用；PromptRenderer 不把 policy/truncation 当成额外业务事实解释。

## 8.4 Trace Reader

新增生产只读端口：

```python
class AgentTraceReader(Protocol):
    async def list_steps(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> tuple[RunStep, ...]: ...
```

SQL Adapter 必须先通过 `AgentRun.user_id` 验证归属，再按 index 返回领域 `RunStep`。不存在或不属于用户统一返回 not-found，不泄漏跨用户 run 是否存在。

---

# 9. Eval Case Contract

## 9.1 Loader

Case 使用 YAML 描述，并通过：

```text
yaml.safe_load
  ↓
Pydantic model_validate
  ↓
cross-case validation
```

所有模型使用：

```python
ConfigDict(extra="forbid")
```

加载阶段必须拒绝：

- 重复 Case ID。
- 未知 Suite、Execution Mode、Fixture 或 Grader Kind。
- 无时区 datetime。
- 空 turns / query。
- 不存在的 fixture alias。
- 不适用于当前 execution mode 的 expectation。
- 未知 schema version。

## 9.2 Case Types

不使用一个包含大量可空字段的万能 `ExpectedBehavior`。Case 按 execution mode 使用 discriminated union：

```text
AgentEvalCase
MemoryRetrievalEvalCase
MemoryLifecycleEvalCase
ContextInjectionEvalCase
```

公共字段：

```text
schema_version
id
suite
fixture
tags
```

Agent Case 包含：

```text
turns[]
expectation
```

每个 Turn 只允许：

```text
input
timestamp
```

所有消息均为 user input；不提供伪造 assistant/system message 的通用 role 字段。

Memory Retrieval Case 包含：

```text
query
as_of
semantic_limit / episode_limit（必须不超过生产上限）
expectation
```

Memory Lifecycle Case 包含按时间排列的 correction turns、worker barrier 和独立 retrieval query。

## 9.3 Fixture Alias

YAML 不保存运行时 UUID。Fixture 返回：

```python
@dataclass(frozen=True)
class EvalFixtureRefs:
    user_id: UUID
    ids: Mapping[str, UUID]
```

Case 通过稳定逻辑名引用：

```yaml
required_memories:
  - current_weekly_frequency
```

Loader / Runner 在执行前把 alias 解析为当前 Trial 的真实 UUID。未知 alias 必须在开始模型调用前失败。

---

# 10. Fixture Strategy

Fixture Registry 是固定白名单：

```python
FIXTURES = {
    "runner_vertical_slice": seed_runner_vertical_slice,
    "runner_normal_fatigue": seed_runner_normal_fatigue,
    "runner_without_state": seed_runner_without_state,
    "semantic_memory_distractors": seed_semantic_memory_distractors,
    "fatigue_episode_history": seed_fatigue_episode_history,
    "schedule_preference_correction": seed_schedule_preference_correction,
    "training_frequency_correction": seed_training_frequency_correction,
}
```

禁止根据 YAML 字符串动态 import 或执行任意 Python。

规则：

- 静态历史 fixture 可以复用现有 `seed_vertical_slice` 与基础设施 seed builder。
- 任何用于验证持续更新的事实必须经过正式 mutation / Outbox / Worker 路径。
- Memory 必须拥有合法 Evidence，不允许直接插入无来源 Memory。
- Memory Conflict 使用确定性 Extractor 产生候选，但使用正式 Projection Service、Repository merge 与真实 embedding。
- Tool / Coaching Case 注入 No-op Memory Extractor，防止 TurnCommitted 触发与当前评分无关的额外抽取 LLM 调用。
- 所有业务时间冻结在明确的带时区时间；纠正 Turn 必须晚于旧事实。
- 每个 Case / Trial 创建独立用户；不复用其他 Case 的用户或 Thread。

---

# 11. Eval Environment

## 11.1 Database

CLI 只接受：

```text
EVAL_DATABASE_URL
```

在 migration 或清理前必须同时满足：

1. URL 可以被 SQLAlchemy 安全解析。
2. 数据库名精确为 `run_coach_eval`。
3. 规范化 URL 不等于当前 `DATABASE_URL`。
4. 规范化 URL 不等于当前 `TEST_DATABASE_URL`。
5. 实际连接后的 `current_database()` 仍为 `run_coach_eval`。

任何条件不满足立即退出 ERROR，且日志不得输出含密码的原始 URL。

完整 Eval Run 开始时：

```text
validate target
  ↓
alembic upgrade head
  ↓
TRUNCATE known application tables RESTART IDENTITY CASCADE
  ↓
run cases
```

只在完整 Run 开始时全量重置一次；Case / Trial 之间使用不同 user_id 隔离。

## 11.2 Container

Eval 复用现有 Settings 和 `build_container()`：

- `database_url` 强制替换为已验证的 EVAL_DATABASE_URL。
- `--model` 可覆盖 `llm_model`。
- `--trials` 只影响 Runner，不进入生产 Settings。
- Case 不得覆盖 `agent_max_steps`、Tool Registry 或业务策略版本。

每个 Case / Trial 构建与其 execution mode 对应的 Container，并在完成后 dispose engine。

## 11.3 Request and Thread

Agent Turn 必须使用完整 `RequestContext`：

```text
trusted user_id
new request_id
new trace_id
case-defined timestamp
```

同一 Case 的后续 Turn 必须传递第一次 ChatResult 返回的 thread_id。需要证明 Memory 已成为长期认知的查询必须显式创建新 Thread。

---

# 12. Durable Consistency Barrier

`TurnCommitted` 会同时路由：

```text
finalize_terminal_turn
project_semantic_memory
```

因此 ChatService 返回不代表 PlanChange 或 Memory 已完成最终业务状态。

Eval 使用与现有测试相同的正式 Publisher、Consumer、Handler，但 Queue 为进程内收集实现：

```text
Outbox Publisher
  ↓
Collecting Queue
  ↓
Consumer Runner
  ↓
Durable Task Handlers
```

禁止：

- 直接调用 `promote_draft_for_turn()` 伪造 Worker 完成。
- 直接调用 Memory Repository 绕过 Projection。
- 启动真实 Redis 来评价 Agent 行为。

Barrier 必须持续排空新产生的 Outbox，直到没有新 claim。任何 task 进入 failed、dead-lettered、quarantined，或超过配置的有界排空次数，都使 Trial 进入 ERROR。

---

# 13. Trace Adapter

`EvalTrace` 是生产 `RunStep` 的只读 Adapter，不是新 Trace 模型。

它必须提供：

```text
context_manifest
attempted_tool_calls
successful_tool_calls
failed_tool_calls
observations_by_call_id
search_hits
final_answer
```

初始化时必须验证：

- index 严格递增且唯一。
- 最多一个 context 和一个 final。
- 每个 observation 都存在对应 tool_call。
- tool_call / observation 的 `call_id` 与 `model_call_id` 一致。
- completed run 必须包含 final；failed/cancelled run 不伪造 final。

Trace 结构损坏属于 ERROR，不交给行为 Grader 猜测。

---

# 14. Graders

## 14.1 Common Result

```python
@dataclass(frozen=True)
class GradeResult:
    grader: str
    passed: bool
    score: float
    reason_code: str
    details: dict[str, object]
```

Case 只有全部 Grader 通过才算该 Trial PASS。

## 14.2 Tool Grader

Tool expectation：

```text
required_successful_tools
required_discoveries
forbidden_tool_attempts
max_tool_attempts
```

判定：

- required tool 必须存在成功 Observation，仅出现 tool_call 不算成功。
- forbidden tool 只要出现 tool_call 即失败，即使 Runtime 返回 `tool_not_available` 或 `tool_not_authorized`。
- required discovery 必须存在成功 search_tools Observation，目标出现在 hits，且目标之后执行成功。
- 不要求完整 Tool 序列与 Gold 完全一致。
- `max_tool_attempts` 统计所有 tool_call，包括失败尝试与 search_tools。

## 14.3 Memory Retrieval Grader

分别评价 Semantic 与 Episodic：

```text
required IDs included
forbidden IDs excluded
selected IDs
selected count
truncated flag
policy version
```

当前 Retrieval Service 暴露的是经过条数与字符预算后的最终集合，因此指标名称为：

```text
Semantic Recall@ConfiguredLimit
Episode Recall@ConfiguredLimit
```

不能把该结果称为“候选召回率”，因为 MVP 不暴露预算裁剪前的 candidate ranking。

## 14.4 Memory Conflict Grader

必须同时检查：

- 旧 Memory status = superseded。
- 新 Memory status = active。
- 旧 Memory.superseded_by_id = 新 Memory.id。
- 新 Thread 的 Retrieval 包含新 Memory。
- 新 Thread 的 Retrieval 不包含旧 Memory。

## 14.5 Context Injection Grader

检查目标 alias 对应 ID 是否真实出现在 CONTEXT RunStep 的 semantic / episodic IDs 中，并同时报告 policy version 与 truncation。

## 14.6 Coaching Decision Grader

正例必须检查：

- 当前 Turn 创建 PlanChange。
- `source_turn_id / source_run_id` 与当前 Trial 一致。
- Worker drain 后 status = pending_confirmation。
- reason 非空。
- based-on Plan / Athlete State version 与 fixture 一致。
- Active Plan 的 ID 和 version 未变化。

负例必须检查：

- 当前 Turn / Run 没有创建 PlanChange。
- Active Plan 的 ID 和 version 未变化。

只读取“该用户最新 PlanChange”不足以证明当前 Case 的结果，必须按 source identity 关联。

---

# 15. MVP Case Set

## 15.1 Tool — 7 Cases

| ID | Primary capability | Input intent | Required outcome |
| --- | --- | --- | --- |
| `tool_recent_001` | Selection | 列出最近 7 天训练记录 | `get_recent_workouts` 成功 |
| `tool_feedback_001` | Selection | 只读取上次间歇课的主观反馈 | `get_workout_feedback` 成功，不用客观分析替代 |
| `tool_workout_analysis_001` | Selection | 分析 session-RPE 与是否为质量课 | `analyze_workout` 成功 |
| `tool_discovery_detail_001` | Discovery | 查看上次间歇课完整客观数据和心率 | search 命中并成功执行 `get_workout_detail` |
| `tool_discovery_load_001` | Discovery | 比较最近与此前 7 天负荷及 sRPE 覆盖 | search 命中并成功执行 `analyze_training_load` |
| `tool_governance_fatigue_001` | Governance | 正常训练后只是稍微疲劳 | 不尝试 `propose_plan_adaptation` |
| `tool_governance_context_001` | Governance | 询问 WorkingContext 已有比赛目标 | 不调用 Tool，不做无意义 search |

Case 可以有多项 Grader；Primary capability 只决定指标归类，不阻止隐藏工具 Case 同时验证 Discovery。

## 15.2 Memory — 5 Cases

| ID | Execution level | Required outcome |
| --- | --- | --- |
| `memory_semantic_recall_001` | Memory Retrieval | 可用训练时间约束在干扰项中进入 Semantic 结果 |
| `memory_episode_recall_001` | Memory Retrieval | 相似疲劳与恢复经历进入 Episode 结果 |
| `memory_conflict_schedule_001` | Memory Lifecycle | 晚间训练偏好被较新的晨间训练偏好取代 |
| `memory_conflict_frequency_001` | Memory Lifecycle | 每周最多 3 次被较新的每周可训练 5 次取代 |
| `memory_context_injection_001` | Context Injection | 目标 Memory ID 真实出现在 CONTEXT RunStep |

两个 Conflict Case 的最终查询必须使用新 Thread。

## 15.3 Coaching — 3 Cases

| ID | Evidence | Required outcome |
| --- | --- | --- |
| `coaching_adapt_001` | HIGH fatigue 且未来窗口有质量课 | 创建本 Run 的 pending PlanChange，Active Plan 不变 |
| `coaching_no_adapt_001` | 正常训练后的轻微疲劳 | 不创建 PlanChange |
| `coaching_insufficient_001` | 缺少可信 Athlete State | 不创建 PlanChange |

正反例同时存在，避免把“用户提到累”错误学习成固定触发计划调整。

---

# 16. Result Model and Status

结果层级：

```text
EvalRunReport
  └── EvalCaseResult
        └── EvalTrialResult
              └── EvalTurnResult
```

`EvalTurnResult` 保存：

```text
thread_id
turn_id
run_id
input
timestamp
context_manifest
run_steps
final_answer
duration_ms
```

`EvalTrialResult` 保存 grader results 与：

```text
PASS
FAIL
ERROR
```

Case 聚合：

- 所有 Trial PASS → PASS。
- 所有 Trial FAIL → FAIL。
- Trial 同时存在 PASS 与 FAIL → UNSTABLE。
- 任一 Trial ERROR → ERROR。

默认 `trials=1`。正式基线使用 `--trials 3`；3/3 才算稳定 PASS，1/3 或 2/3 均为 UNSTABLE。

---

# 17. Metrics

报告必须同时显示：

```text
Raw Case Pass Rate
Suite Macro Score
```

Raw Case Pass Rate：15 个 Case 等权。

Suite Macro Score：Tool、Memory、Coaching 三个 Suite 的平均得分等权，防止 7 个 Tool Case 主导总体结论。

辅助指标：

```text
Tool Required Success Rate
Tool Discovery Success Rate
Forbidden Tool Attempt Rate
Semantic Recall@8
Episode Recall@4
Memory Conflict Accuracy
Context Injection Accuracy
Coaching Decision Accuracy
```

`Unnecessary Tool Rate` 不在 MVP 中使用，因为仅有 forbidden list 时无法证明所有其余调用都“不必要”。治理指标使用语义明确的 `Forbidden Tool Attempt Rate`。

ERROR 不计为行为失败，但必须单独显示数量，并使整次 CLI 退出为 ERROR。不得通过排除 ERROR 后只展示漂亮 Pass Rate 掩盖环境失败。

---

# 18. CLI

入口：

```text
uv run python -m app.evals.cli run
```

支持：

```text
--suite tool|memory|coaching
--case <case-id>
--trials <positive-int>
--model <model-name>
--baseline <report.json>
--output <report.json>
```

规则：

- `--suite` 与 `--case` 可以组合，但 case 必须属于所选 suite。
- `--trials` 默认 1；必须大于 0。
- `--model` 只覆盖本次 Eval Container 的模型配置。
- `--output` 省略时写入 `.eval-results/<UTC timestamp>-<short git sha>.json`。
- Case / suite 过滤后为空立即 ERROR。

退出码：

```text
0 = 全部 Case PASS
1 = 至少一个 FAIL 或 UNSTABLE，且没有 ERROR
2 = 至少一个 ERROR，或启动 / 配置 / Schema 失败
```

---

# 19. JSON Artifact and Baseline

JSON 顶层必须包含：

```text
schema_version
run_id
started_at / completed_at
selected_suites / selected_cases
trials
configured_model
prompt_version
memory_policy_version
git_sha
git_dirty
duration_ms
summary
case_results
```

保存全部合成场景轨迹：

- Context Manifest。
- Tool 参数与 Observation。
- Final Answer。
- Grade reason code 与 details。

必须过滤：

```text
API key
JWT
数据库连接串
环境变量原值
异常 traceback 中的敏感基础设施信息
```

`--baseline` 要求 baseline JSON schema version 可识别，并报告：

```text
new failures
recovered cases
PASS → UNSTABLE
UNSTABLE → PASS
suite metric delta
added / removed cases
model / prompt / memory policy / git differences
```

配置不同只产生显著 warning，不禁止比较。Baseline 只负责差异展示；当前运行存在 FAIL / UNSTABLE 时仍返回退出码 1。

---

# 20. Provenance

MVP 记录：

```text
configured model
prompt version
memory policy version
git commit SHA
git dirty flag
trial number
case schema version
start / end time
total latency
```

Prompt 必须新增显式版本常量；Prompt 语义改变时必须同步提升版本。

MVP 不记录逐次模型调用 token usage。当前流式 Provider 不返回 usage，且 LLMReasoner 会把 ModelResponse 归一成 Action；为成本分析改造该链路属于后续 Phase。

若无法读取 git SHA，开发回归 CLI 立即 ERROR，不写 `unknown` 伪装成可追溯结果。

---

# 21. Final Answer Boundary

MVP 不自动评价最终自由文本质量。

原因：

- 关键词 / 正则对中文同义表达误判严重。
- Tool 调用正确不代表最终回答完全忠于证据。
- Memory 被注入不代表模型正确使用了 Memory。
- 在没有结构化决策输出或 Judge 合同前，不能伪装 deterministic grader 已解决自由文本质量。

报告必须明确展示：

> **PASS 表示 Trace、Context 与 Domain Outcome 满足 Case 预期，不代表语言质量或完整事实一致性已经通过评估。**

后续可以独立增加受版本控制的 LLM Judge，但不能改变 MVP 指标的历史语义。

---

# 22. Failure Semantics

行为 FAIL 示例：

- required Tool 没有成功执行。
- 模型尝试调用 forbidden Tool。
- search_tools 未发现目标或发现后未成功执行。
- required Memory 未进入 Retrieval / Context。
- 旧冲突 Memory 仍 active 或仍被召回。
- 应调整 Case 没有形成 pending PlanChange。
- 不应调整 Case 创建了 PlanChange。

ERROR 示例：

- Case / YAML Schema 非法。
- fixture / alias 不存在。
- Eval 数据库校验失败。
- LLM / Embedding Provider 调用失败。
- RunStep 结构损坏。
- Worker task failed、dead-lettered、quarantined 或无法排空。
- Trace / Domain State 无法读取。
- JSON Artifact 无法写入。

不得把 ERROR 当作 FAIL，也不得在 Overall Pass Rate 中静默忽略 ERROR。

---

# 23. Test Strategy

## 23.1 Focused Tests

仅为非平凡的纯逻辑增加 focused tests：

- YAML strict validation 与 discriminated union。
- duplicate Case ID、unknown fixture / alias rejection。
- ToolCall / Observation pairing 与 Trace invariant。
- required-success、forbidden-attempt、discovery ordering Grader。
- multi-trial PASS / FAIL / UNSTABLE / ERROR 聚合。
- Raw Pass Rate 与 Suite Macro Score。
- baseline diff。
- Eval database URL / actual database guard。
- JSON sensitive-field redaction。

不为简单 dataclass、CLI 参数转发或薄格式化函数机械补测试。

## 23.2 Integration Scenarios

使用真实 PostgreSQL 验证：

1. Context RunStep 被持久化，并能通过 user-scoped TraceReader 读取。
2. 跨用户读取 run 不泄漏存在性。
3. Scripted Tool 轨迹能由 EvalTrace 正确重建。
4. Memory correction 经 Outbox / in-process Worker 后完成 supersession。
5. 新 Thread 只召回新 Memory，不依赖旧 Thread history。
6. Context Injection Case 的目标 ID 出现在 Context RunStep。
7. PlanChange 在 ChatService 返回后仍为 DRAFT，drain 后才进入 PENDING_CONFIRMATION。
8. Coaching Grader 只接受当前 source turn/run 的 PlanChange。
9. 不安全数据库名或生产 URL 绝不执行 migration / truncate。

## 23.3 Manual Real LLM Acceptance

```text
uv run python -m app.evals.cli run
uv run python -m app.evals.cli run --trials 3
uv run python -m app.evals.cli run --baseline <first-report.json>
```

真实 LLM Acceptance 不要求第一次就 100% PASS；Eval 的价值正是暴露失败。完成标准是：

- 15 个 Case 均能执行到 PASS / FAIL / UNSTABLE，而不是 ERROR。
- 每个失败都有可读 reason code、Trace、Context 与 Domain Outcome。
- `--trials 3` 能正确暴露随机不稳定 Case。
- baseline diff 能正确显示回归与恢复。

现有 Phase 1–5 tests 必须继续通过。

---

# 24. Implementation Order

1. **Contract first**：确认本 Phase 文档与 Architecture 一致，冻结 Case / Result / Status 语义。
2. **Context observability**：实现 MemoryContextResult、CONTEXT RunStep 与现有测试更新。
3. **Trace read path**：实现 user-scoped AgentTraceReader 与 EvalTrace invariants。
4. **Core schema**：实现 Pydantic Case unions、YAML Loader、cross-case validation 与 fixture alias。
5. **Environment safety**：实现 EVAL_DATABASE_URL guard、migration、reset 与 Container lifecycle。
6. **Durable barrier**：复用 Publisher / Consumer / Handler 实现有界 in-process drain。
7. **Tool suite**：先实现 Tool Grader 与 7 个 Case，跑通 Real LLM 主链。
8. **Memory suite**：实现 Semantic / Episode Retrieval、两个 Conflict 与 Context Injection。
9. **Coaching suite**：实现 source-correlated Domain reader / Grader 与 3 个正反例。
10. **Reporting**：实现 Trial 聚合、指标、CLI、JSON schema 与退出码。
11. **Baseline**：实现兼容校验与 case/suite delta。
12. **Acceptance**：运行 focused / integration / Phase 1–5 regression，并生成第一份 3-Trial baseline。

不得先写 15 个 YAML，再反推 Runner 和 Grader 语义；不得以真实模型偶然跑通代替 Harness 合同测试。

---

# 25. Definition of Done

Phase 6 完成必须同时满足：

- [ ] `app/evals` 是唯一 Eval 实现，不存在包外第二套 Harness。
- [ ] Case YAML 使用严格 schema，可通过 fixture alias 添加合成场景。
- [ ] Context RunStep 记录实际 Memory IDs、领域版本与检索策略，不保存敏感正文。
- [ ] AgentTraceReader 按 user_id 隔离并返回领域 RunStep。
- [ ] EvalTrace 能可靠配对 ToolCall / Observation 并检测损坏轨迹。
- [ ] Tool / Coaching 真实 Case 从 ChatService 使用 Real LLM 执行。
- [ ] Memory Retrieval / Lifecycle / Context Injection 按各自真实边界执行。
- [ ] Durable consistency barrier 复用正式 Publisher / Consumer / Handler。
- [ ] 7 Tool + 5 Memory + 3 Coaching 共 15 个 Case 可运行。
- [ ] 禁止工具按“尝试即失败”评分，Discovery 同时验证 search hit 与执行成功。
- [ ] Memory Conflict 使用新 Thread 验证新知识，旧知识已 superseded。
- [ ] Coaching Outcome 与当前 source turn/run 关联，Active Plan 未被直接修改。
- [ ] PASS / FAIL / UNSTABLE / ERROR 与 CLI 退出码语义稳定。
- [ ] CLI 同时输出终端摘要与完整 JSON artifact。
- [ ] `--baseline` 能显示新增失败、恢复、稳定性与 Suite 指标变化。
- [ ] 报告包含模型配置、Prompt / Memory policy、git SHA、dirty flag、Trial 与总耗时。
- [ ] 独立 Eval DB guard 在任何 migration / truncate 之前执行。
- [ ] 真实 LLM 默认手动运行，不作为普通 PR 强门禁。
- [ ] 全部 Harness focused / integration tests 与 Phase 1–5 regressions 通过。
- [ ] 第一份 `--trials 3` JSON baseline 已生成，且所有 Case 无 ERROR。

---

# 26. Future Space

MVP 稳定后可独立演进：

```text
LLM-as-a-Judge for evidence grounding
Memory Extraction precision / recall
Prompt and model comparison matrix
Per-model token and cost telemetry
Nightly scheduled evaluation
Long conversation simulator
Safety / hallucination red-team suite
Web dashboard and historical storage
```

这些能力必须通过新的 schema / metric version 增量加入，不能改变 Phase 6 MVP 已发布指标的历史含义。

