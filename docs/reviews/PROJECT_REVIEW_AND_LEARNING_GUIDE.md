# Run Coach Agent 项目 Review 与入门学习指南

> Review 日期：2026-09-02  
> 范围：顶层架构、Phase 1–5 合同与实现说明、Agent/Tool/Memory/Coaching/Worker 主链路、代表性测试与本地静态验证。

## 一句话结论

这是一个**架构意识显著高于普通 Agent Demo、可靠性底座接近生产系统，但业务智能与评测体系仍处于早期**的项目。

它最值得学习的不是 Prompt，而是四件事：

1. 如何把 Agent Runtime 与 Conversation、Domain、Memory、Tool、Infrastructure 分开；
2. 如何让模型只能通过受治理的领域能力行动；
3. 如何让长期记忆有证据、可纠正、可回放；
4. 如何把一次对话后的学习做成可恢复、可幂等的异步闭环。

如果把它当作“跑步教练产品”，当前大约是一个扎实的技术底座和可运行垂直切片；如果把它当作“学习高级 Agent 工程的教材”，价值很高。

## 综合评价

| 维度 | 评价 | 说明 |
| --- | --- | --- |
| 架构边界 | 9/10 | Canonical Fact、Derived State、Memory、Runtime State 的所有权划分非常清楚 |
| Agent Harness | 8/10 | Reason–Act–Observe、生命周期、轨迹和 Tool 治理完整；扩展机制仍偏项目内定制 |
| Memory | 8.5/10 | Evidence、双时态、纠正/取代、幂等投影明显优于“向量库即记忆” |
| 可靠性 | 8.5/10 | Outbox、receipt、重试、dead letter、recovery 和并发边界设计成熟 |
| 跑步教练智能 | 6/10 | 当前以 sRPE、窗口统计和规则状态为主，领域深度尚未匹配底座复杂度 |
| Safety / Eval | 4/10 | 顶层文档定义明确，但代码中尚未形成独立、可持续的质量闭环 |
| 工程交付成熟度 | 6.5/10 | 测试质量不错；文档状态、Lint 基线、CI 与可观测性仍有治理缺口 |
| 学习价值 | 9/10 | 很适合沿真实调用链学习 Agent 工程，而不是从框架 API 开始背概念 |

## 最优秀的设计

### 1. 数据所有权是项目真正的“主心骨”

`docs/ARCHITECTURE.md` 没有把所有东西都称为 Memory，而是明确区分：

- PostgreSQL Canonical Facts：发生过什么；
- Athlete State Snapshot：跑者现在怎么样；
- Long-term Memory：Agent 长期如何理解这个人；
- Reasoning State：本次 Run 正在想什么、调用过什么。

这比常见的“聊天记录 + 向量库 + 大 Prompt”可靠得多。尤其正确的是：训练事实不能被 Memory 替代，失败或取消的 Turn 不能污染长期记忆，Tool Call/Observation 不能混入 canonical conversation。

### 2. Harness 小而清楚，核心循环没有被业务污染

`AgentRuntime` 只做：

```text
Context → Reason → Action → Observation → … → Final
```

`ChatService` 拥有 Turn/Message/AgentRun 生命周期和两个短事务；`ToolRuntime` 隐藏 Registry/Search/Resolver/Executor；`LLMProvider` 隔离厂商协议。这个边界很适合学习：每个对象都能用一句话回答“它拥有哪种状态、哪种失败、哪种事务”。

项目还做对了几个容易忽略的细节：

- 每个 Run 创建独立 ToolSession，发现结果不跨 Turn 泄漏；
- 每轮重新计算 visible tools，`registered != visible != executable`；
- 模型参数与可信 `ToolExecutionContext` 分离，模型无法注入 `user_id`；
- mutating tool 不允许模型直接执行，计划修改先产生草案，再由用户确认；
- Cancellation 不被误归一化为普通 Tool 错误。

### 3. Memory 的设计比多数开源“记忆插件”更审慎

这个项目没有把“LLM 抽出一句话并写向量库”当作完成。Semantic Memory 具有来源、有效时间、状态、证据组与纠正关系；Episode 具有触发、干预、结果证据；Projection 有稳定 identity、fingerprint 和版本；Retrieval 有双时间过滤、确定性重排和预算。

尤其值得保留的原则是：

> Memory 是带来源的派生认知，不是新的事实源。

这也是它相对通用 Memory 系统最有业务价值的地方：不是追求“记得更多”，而是追求“只在正确时间相信有依据的记忆”。

### 4. 异步学习闭环不是 best-effort 回调

Phase 5 把 post-commit 学习从进程内 listener 提升为：

```text
Canonical mutation + Outbox（同事务）
→ Redis/ARQ 调度
→ Consumer receipt
→ Application Service
→ 幂等业务结果
```

项目清楚地区分 Outbox、Queue Job、Consumer Receipt，并处理 enqueue 后崩溃、service commit 后崩溃、重复投递、旧事件晚到、Redis 丢失与 poison message。这已经不是 Demo 级“后台任务”，而是可靠异步业务的完整思维模型。

### 5. 测试关注真实风险

代表性测试不是只断言 HTTP 200，而是在验证：

- Reason → Tool → Observation → Final 的 RunStep 顺序和 call id 配对；
- 当前输入只进入 Context 一次；
- 隐藏 Tool 无法猜名调用，写 Tool 无法越权；
- 计划版本过期不能覆盖新计划；
- failed/cancelled Turn 不产生 Memory；
- 相同向量下仍保持跨用户隔离；
- 重复/乱序 Worker delivery 只产生一个逻辑结果。

这套测试观很值得直接学习。

## 主要问题与风险

### P0：Safety 与 Eval 还没有成为代码里的系统能力

顶层架构已经把 Safety 优先级和 Eval 输入定义得很好，但当前目录与主链路没有与之匹配的独立安全规则/评测模块。对跑步训练这种带健康风险的决策系统，仅靠 System Prompt 中的谨慎措辞不够。

建议下一阶段先实现：

1. 确定性高风险信号与行动限制，例如胸痛、晕厥、急性伤痛、异常心率等触发停止训练/建议就医；
2. Coaching Decision 的 evidence citation contract；
3. 一组固定场景 Eval：工具选择、证据使用、过度推断、危险建议、用户隔离；
4. 线上 trace → 离线 eval dataset 的采样与脱敏链路。

不要先扩更多工具或更多 Memory 类型。

### P1：基础设施复杂度已经领先于 Running Intelligence

当前训练智能主要由 7/14 天窗口、session-RPE 覆盖率、质量课、近期反馈和确定性规则构成。它的优点是保守、可解释，但还不足以支撑“长期自适应教练”的产品承诺。

明显缺口包括：

- 缺少 Garmin/Strava/COROS 等正式 ingestion adapter；
- 缺少更丰富的训练反应建模、负荷/恢复趋势与个体基线；
- 计划适配策略仍较窄，更多是受约束的降负荷垂直切片；
- 没有用后续训练结果系统评估一次建议是否有效。

建议维持模块化单体，不再增加平台抽象，把主要投入转到 domain model、evidence quality 和 coaching eval。

### P1：Memory 的“自动学习面”仍不完整

`project_committed_turn()` 已由 durable TurnCommitted 自动触发，适合抽取用户明示偏好；`project_evidence_set()` 支持从正式证据推导 semantic memory，但当前 Worker 路由没有相应的持续触发链。因此系统自动学到的语义记忆主要还是“用户说过的长期偏好/约束”，训练事实归纳能力尚未闭环。

Episode 使用确定性 detector 是合理的保守起点，但当前只有两类 episode，摘要模板也较固定。下一步应先定义哪些**领域结论值得长期记住**及其最低独立证据要求，再增加触发器；不要让 LLM 任意总结所有训练数据。

### P1：Harness 可运行，但还不是 pi 那类通用可组合 harness

项目的核心循环很干净，但扩展主要依赖 `bootstrap.py` 中的静态装配和项目内 ToolProvider。与优秀轻量 harness 相比，仍缺：

- 稳定的 extension/hook 接缝；
- 可替换的 context compaction/token accounting；
- Tool result 的统一全局 token/size 治理（当前更多由各工具自行限制）；
- 多模型能力协商与 provider conformance tests；
- 可复用的 session persistence/branching/resume contract。

这里不建议直接“框架化”。先从一个真实需求切出最小 extension seam，例如 `ContextPolicy` 或 `RunHook`，并用两个实现证明它确实需要抽象。

### P2：文档状态和交付状态存在漂移

README 宣称 Phase 5 已完成、回归基线为 216 passed；但 Phase 5 合同仍标记为 `Draft`，Definition of Done 清单仍全部未勾选。Review 当天的本地验证结果是：

- `uv run pytest tests/unit -q`：98 passed；
- `uv run ruff check app tests`：1 个错误，`app/api/routes/chat.py` 的 `AsyncGenerator` 应从 `collections.abc` 导入；
- 完整 PostgreSQL/Redis 集成回归未在本次 review 中执行；
- 前端 typecheck 因当前执行环境无法创建 npm 进程，未取得结果。

建议用 CI 作为唯一可见状态来源，在 README 显示当前 commit 的 lint/unit/integration 状态；Phase 文档进入交付后改为 Accepted/Implemented，并记录验收 commit，而不是留下互相冲突的文本声明。

### P2：生产可观测性与运维治理尚未闭环

已有结构化日志和数据库审计，这是好基础；但缺少 trace backend、指标、告警、Outbox 清理和 dead-letter 管理界面。对于 durable worker，至少应监控：outbox backlog age、publish failure、receipt retry/dead-letter、projection lag、每类任务耗时与每用户积压隔离。

## 与 pi / Mem0 的正确比较方式

不要问“谁功能更多”，要比较它们分别优化什么。

### 与 pi 类 harness 比

pi 类项目最值得学的是**极小稳定核心 + 可组合扩展**：让模型循环、工具、会话、上下文处理保持简单，并把 UI、provider、持久化或扩展能力放到清晰接缝。

Run Coach 的优势是领域事务、安全边界和可靠异步闭环更强；劣势是装配更重、复用性更低。正确方向不是把 Run Coach 改成通用框架，而是保持领域系统身份，同时让 `AgentRuntime`、`ToolRuntime`、`Reasoner` 的接缝继续小而稳定。

### 与 Mem0 类 Memory 系统比

Mem0 最值得学的是把 memory extraction/update/retrieval 做成独立生命周期，并围绕 add/search/update/history 提供可操作接口与评测。Run Coach 的 Evidence、Canonical Fact 分离和双时态语义更保守，也更适合高风险领域；但它的 memory 自动化覆盖、评测和运营接口还不如成熟通用系统完整。

因此应借鉴 Mem0 的工程化与评测，不应照搬“所有内容先抽成 Memory”的数据模型。

开源项目的一手资料核验与详细引用另见同目录的 `open-source-agent-reference.md`。

## 推荐入门路线

### 第 0 步：先跑通一条垂直链，不要先通读所有文件

准备 PostgreSQL + pgvector、Redis、Python 3.12、uv 和 Node 20，按根 README 启动并 seed demo。然后只完成一个动作：在前端问“我最近训练状态怎么样”，记录一次 request 的 `thread_id/turn_id/run_id`。

学习目标：知道系统“能跑起来”时有哪些进程和持久化对象，而不是马上理解每个类。

### 第 1 步：用一轮对话理解 Harness（1–2 天）

按这个顺序读：

1. `backend/app/agent/application/chat_service.py`
2. `backend/app/agent/runtime/agent_runtime.py`
3. `backend/app/agent/context/assembler.py`
4. `backend/app/agent/reasoning/prompt_renderer.py`
5. `backend/app/tools/runtime.py`
6. `backend/app/tools/executor/executor.py`
7. `backend/tests/integration/test_agent_runtime_loop.py`

边读边画出：谁创建 Turn、谁持有事务、谁决定下一步、谁执行工具、谁保存 Trace、谁提交 Assistant Message。

完成标准：你能不看代码解释为什么 `AgentRuntime` 不能提交 Turn，为什么 ToolSession 不能跨 Turn 复用。

### 第 2 步：沿一个 Tool 读穿领域边界（1–2 天）

选择 `analyze_training_load`：

```text
Tool Definition
→ ToolExecutor
→ TrainingAnalysisService
→ training_load.py 纯逻辑
→ Repository Port
→ SQLAlchemy Repository
→ Observation
```

然后读 `test_coaching_intelligence.py`。重点不是 Python 语法，而是区分查询、分析、草案和真正 mutation 的权限等级。

完成标准：自己新增一个只读小工具，例如“查询最近一次质量课”，并保持身份来自 `ToolExecutionContext`、参数模型禁止多余字段、结果有明确预算。

### 第 3 步：理解 Memory 不是向量库（2–3 天）

按这个顺序读：

1. `memory/domain/semantic.py`、`evidence.py`、`episode.py`
2. `semantic_projection_service.py`
3. `episode_projection_service.py`
4. `retrieval_service.py`
5. SQLAlchemy memory repository
6. `test_memory_vertical_slice.py`

画两张图：`TurnCommitted → Semantic Memory` 与 `AthleteState/PlanChange → Episode`。在每个箭头上写清楚 evidence、identity、事务和幂等依据。

完成标准：你能解释“相同向量为什么不能串用户”“为什么失败 Turn 不得有 projection receipt”“显式纠正后为何历史 as_of 仍能看到旧记忆”。

### 第 4 步：理解长期 Agent 的可靠异步闭环（2–3 天）

读：

1. `common/events.py` 与两个 durable event contracts；
2. Outbox writer/repository；
3. Worker routing、publisher、consumer、handlers；
4. recovery/replay 脚本；
5. `test_arq_delivery.py`、`test_worker_recovery_boundaries.py`、`test_continuous_state_worker.py`。

对同一个事件分别推演四种故障：提交前崩溃、enqueue 后崩溃、业务提交后 receipt 完成前崩溃、旧事件晚到。

完成标准：能解释 transport 的 at-least-once 与业务的 exactly-once logical result 为什么不矛盾。

### 第 5 步：再读顶层架构并做一次反向审计（1 天）

此时再完整阅读 `docs/ARCHITECTURE.md`，逐条抽查 Architectural Invariants。给每条标记：

- 已由代码实现；
- 仅文档目标；
- 有测试证据；
- 当前存在偏离。

这样读架构文档会从“概念很多”变成“能定位到 owner 和证据”。

## 最适合作为第一个贡献的任务

建议按难度选择：

1. **低风险**：修复 Ruff 错误并建立最小 CI（ruff + unit），让 README 状态来自 CI；
2. **中风险**：为所有 Tool Observation 建立统一 size/token budget policy，并补一个超大结果场景测试；
3. **高价值**：实现第一版 deterministic Safety Policy + 场景 Eval，不依赖 LLM 自觉；
4. **领域方向**：接入一种真实训练数据源，但写入必须复用 Workout/Feedback command + outbox 边界；
5. **Memory 方向**：为一个严格定义的 inferred memory 建立 canonical evidence trigger、独立证据门槛和 eval。

不建议把“增加一个新 Agent 框架”“改成微服务”“引入通用 workflow engine”作为第一个贡献，这些会绕开项目当前最重要的产品问题。

## 最终建议

未来 1–2 个阶段的优先级应是：

```text
Safety + Eval
→ 真实训练数据接入
→ 更强的 Running Intelligence 与建议结果反馈
→ Memory 自动学习覆盖
→ 可观测性/运维完善
→ 最后才考虑 harness 通用化
```

这个项目已经证明作者理解“Agent 不等于 Prompt + Tools”。下一阶段要证明的是：这套可靠底座能否持续产出**更安全、更准确、可被后续训练结果验证的教练决策**。
