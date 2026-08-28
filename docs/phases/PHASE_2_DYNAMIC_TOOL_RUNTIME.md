# Phase 2 — Dynamic Tool Runtime

> Status: Planned
> Depends on: `docs/ARCHITECTURE.md`
> Previous: `docs/phases/PHASE_1_FOUNDATION_AGENT_CORE.md`
> Scope: Tool Definition + Registry + Search + Discovery + Resolver + Executor + Native Model Tool Calling

---

## Problem Statement

Phase 1 已经建立稳定的 Conversation、Agent Runtime、Context、Execution Trace 与 Lifecycle 边界，但 Agent 可调用能力仍由临时的 Capability 方案承载：所有 Capability Schema 被静态放入 `ContextBundle` 并序列化进 system prompt，模型通过手写 JSON 表达下一步 Action，执行则由 `SimpleCapabilityExecutor` 中的名称分发完成。

这套方案只适合验证少量能力的 Reason–Act–Observe 闭环，不能作为长期 Tool 基础设施。随着 Run Coach 增加训练详情、反馈、状态、计划、Memory 和外部数据能力，向每次模型请求注入全部 Schema 会持续扩大上下文、降低 Tool 选择准确性，也无法清楚区分一个 Tool 是“系统已注册”“当前模型可见”还是“当前运行可执行”。静态 Capability 定义与运行时参数校验还可能演化成两套协议，造成模型看到的 Schema 与实际执行行为不一致。

Phase 2 需要在不改变 Phase 1 Agent Core、ChatService 双事务和 Turn 生命周期所有权的前提下，用正式 Dynamic Tool Runtime 完整替换临时 Capability 路径。底层模型正式切换到 native tool calling，不再要求模型在文本中手写 Tool JSON。模型供应商协议仍被封装在 LLM Provider 边界内，AgentRuntime 只认识统一的 `ToolCallAction`、`Observation` 与 `FinalAction`。

初始可见 Tool 集合固定为：

- `search_tools`
- `get_recent_workouts`

其余 Tool 必须由 Agent 在当前 AgentRun 内通过 `search_tools` 动态发现后才能看到和执行。

---

## Solution

建立独立的 Dynamic Tool Runtime，正式提供 Tool Definition、Registry、Keyword Search、Run-local Discovery、Resolver、Executor 与 Tool Session。系统必须始终区分：

```text
Registered
≠
Visible
≠
Executable
```

一次 AgentRun 的目标链路为：

```text
ChatService
    ↓
AgentRuntime
    ↓
ToolRuntime.create_session
    ↓
Resolver 得到初始可见 Tool
    ↓
Reasoner（native tool calling）
    ↓
ToolCallAction
    ↓
ToolExecutor：存在性 / 可见性 / 参数 / 授权 / 超时 / 错误归一化
    ↓
Observation
    ↓
ReasoningState
    ↓
search_tools 可扩展当前 Run 的可见 Tool
    ↓
Reasoner
    ↓
FinalAction
    ↓
ChatService Transaction B
    ↓
TurnCommitted
```

Tool Registry 是 Tool 存在性的唯一事实来源；Search Index 是 Registry 的进程内派生状态；ToolDiscoveryState 只属于当前 AgentRun；Tool Call 与 Observation 继续写入现有 AgentRun / RunStep Execution Trace。Tool 不直接访问 ORM，只能调用 Coaching Application Service。ContextAssembler 不再装配 Tool，ReasoningContext 在每轮推理时单独接收当前可见的 Tool Definition。

Phase 2 完成后，`Capability` 术语与实现路径从 Agent Core 中彻底删除，不保留兼容层或并行执行路径。

---

## User Stories

1. 作为跑者，我希望教练 Agent 能主动寻找完成问题所需的训练能力，从而不必知道或指定具体 Tool 名称。
2. 作为跑者，我希望 Agent 的回答基于实际 Workout 与 WorkoutFeedback，从而避免把模型猜测当作训练事实。
3. 作为跑者，我希望 Tool 只能读取我的数据，从而保证其他用户的训练、目标和计划不会被越权访问。
4. 作为跑者，我希望 Tool 超时或失败时系统明确说明当前证据获取失败，从而不会伪造成功结果。
5. 作为 Agent，我希望运行开始时直接拥有 `search_tools` 与 `get_recent_workouts`，从而可以先使用高频训练数据并按需发现长尾能力。
6. 作为 Agent，我希望通过自然语言描述缺少的能力来搜索 Tool，从而不依赖固定 Intent Router 或硬编码 Workflow。
7. 作为 Agent，我希望搜索命中的 Tool 在下一次 Reasoning 中以完整 native Schema 出现，从而能够按模型协议正确调用。
8. 作为 Agent，我希望已经发现的 Tool 只在当前 AgentRun 内有效，从而不会把一次任务的临时能力选择污染后续 Turn。
9. 作为 Agent，我希望非法 Tool 参数以结构化 Observation 返回，从而可以基于错误修正下一步 Action。
10. 作为 Agent，我希望猜测到但尚未发现的隐藏 Tool 被拒绝，从而 Tool Discovery 是真实执行边界而不只是上下文优化。
11. 作为 Agent 开发者，我希望 Tool 的模型 Schema 与运行时校验来自同一个 Pydantic 参数模型，从而消除双份协议漂移。
12. 作为 Agent 开发者，我希望 AgentRuntime 只依赖 ToolRuntime 的稳定入口，从而 Registry、Search、Resolver 与 Executor 的细节不会泄漏进 Reason–Act–Observe 主循环。
13. 作为 Agent 开发者，我希望 Reasoner 只把 native 模型响应转换为统一 Action，从而不承担 Tool 执行职责。
14. 作为 Agent 开发者，我希望供应商 Tool Calling 协议只存在于 LLM Provider Adapter，从而更换兼容模型时不改 AgentRuntime。
15. 作为 Tool 开发者，我希望通过统一 Registry 注册 executable、metadata 与 search document，从而 Tool 生命周期只有一个事实来源。
16. 作为 Tool 开发者，我希望重复注册同名 Tool 时立即失败，从而不会发生静默覆盖或不确定执行。
17. 作为 Tool 开发者，我希望 Tool 只调用 Application Service，从而保持 Agent、Domain 与 Infrastructure 的架构边界。
18. 作为平台开发者，我希望 Tool 参数不能声明或接收 `user_id`、`thread_id`、`run_id`、`call_id`、`request_id`、`trace_id` 与 `timestamp`，从而可信运行信息只能由 Runtime 注入。
19. 作为平台开发者，我希望 Registry 注销 Tool 后，Search、Resolver 与 Executor 立即不再提供该 Tool，从而不存在过期的可见或可执行能力。
20. 作为平台开发者，我希望 ToolExecutor 统一处理参数验证、可见性、超时和错误归一化，从而每个 Tool 不会重复实现治理逻辑。
21. 作为平台开发者，我希望原生模型一次只能产生一个下一步 Tool Call 或 Final Response，从而 Phase 2 保持确定的单 Action Runtime 语义。
22. 作为平台开发者，我希望不支持 native tool calling 的模型配置直接失败，从而系统不会静默退回文本 JSON 协议。
23. 作为可观测性维护者，我希望 Tool Call 与 Observation 通过同一个内部 UUID `call_id` 关联，从而可以重建一次执行的完整 Trace。
24. 作为可观测性维护者，我希望保留模型返回的 opaque tool-call ID，从而下一轮请求可以按 native tool calling 协议正确回传 Tool Result。
25. 作为前端开发者，我希望 SSE 使用 `tool.started` 与 `tool.completed` 统一表达执行进度，从而 UI 不依赖 Tool Runtime 内部组件。
26. 作为 Eval 开发者，我希望 `search_tools` 本身也进入 RunStep，从而可以评估 Agent 搜索了什么、发现了什么以及随后调用了什么。
27. 作为系统维护者，我希望 Tool Registry、Search Index 与 Discovery State 不新增数据库表，从而 Phase 2 不为进程内短生命周期状态引入无意义持久化。
28. 作为系统维护者，我希望 Phase 1 的 Conversation、Lifecycle、失败与取消场景继续通过，从而 Tool Runtime 替换不会破坏已稳定的系统地基。
29. 作为 Agent，我希望搜索成功但没有匹配 Tool 时得到成功的空结果，从而可以区分“当前没有能力”与“搜索系统故障”。
30. 作为 Agent，我希望 `search_tools` 告诉我的命中集合与本次真正解锁的集合完全一致，从而不会误判当前可调用能力。
31. 作为跑者，我希望取消整个 Turn 时正在执行的 Tool 立即停止，从而取消操作不会被误报成 Tool 超时或执行失败。
32. 作为平台维护者，我希望 Tool Result 有明确的大小边界，从而动态 Tool Schema 节省的上下文不会被无限 Observation 重新占满。

---

## Implementation Decisions

### 1. 正式术语与清理策略

- `Tool` 成为 Agent 可调用能力的唯一正式术语。
- `CapabilityCallAction` 替换为 `ToolCallAction`；`CapabilityExecutionContext` 替换为 `ToolExecutionContext`；`CapabilityStarted/Completed` 替换为 `ToolStarted/Completed`；RunStep kind 从 `capability_call` 替换为 `tool_call`。
- `SimpleCapabilityExecutor`、`CapabilityExecutor`、`CapabilityContextProvider`、静态 Capability Definition 与文本 Action Parser 全部删除。
- 不保留 Capability / Tool 双 API、兼容 shim、静默 fallback 或两条并行 Reasoner 路径。
- 如果数据库中已经存在 `capability_call` RunStep，迁移时将历史值一次性归一化为 `tool_call`；不要求运行时代码继续理解旧值。

### 2. Agent Core 与 Tool Runtime 边界

- AgentRuntime 继续只拥有 Context → Reason → Action → Observation → Reason → Final 主循环。
- AgentRuntime 只通过 ToolRuntime 创建 Session、解析当前可见 Tool 并执行 ToolCallAction，不直接访问 Registry、Search、Resolver 或参数模型。
- Reasoner 不访问 Registry、Search、Executor、Application Service 或 Repository。
- ChatService 继续拥有 Thread、Message、Turn 与 AgentRun 生命周期以及 Transaction A/B；Tool Runtime 不创建或提交 Conversation 对象。
- Tool Runtime 的失败沿现有 ChatService 失败语义收尾；TurnCommitted 仍只能在 Transaction B 成功后发布。

### 3. Registered、Visible 与 Executable

- Registered 表示 Tool 存在于 Registry。
- Visible 表示 Tool 的完整 Schema 当前被提供给 Reasoner。
- Executable 表示 Tool 仍在 Registry 中、当前 Session 可见、参数有效且通过执行治理。
- 可见集合每轮由 Resolver 重新计算，规则为“当前仍注册的 always-on Tool”与“当前仍注册且已发现的 Tool”的并集。
- Registry 是存在性的唯一事实来源。已经发现但随后注销的 Tool 必须立即从 Resolver 与 Executor 中消失。
- 模型猜到隐藏 Tool 名称时返回 `tool_not_available` Observation，绝不能因为 Registry 中存在就执行。

### 4. Tool Definition 与参数协议

- Tool Definition 至少包含唯一名称、模型用途描述、tags、search hint、always-on 标记、risk、source 与 timeout。
- 每个 Tool 使用独立的 Pydantic 参数模型，并配置拒绝未知字段。
- 模型可见 JSON Schema 由参数模型生成，Runtime 也使用同一模型验证；禁止独立手写第二份 Schema。
- 缺字段、多字段、类型错误和范围错误统一返回 `invalid_arguments` Observation。
- Runtime 不自动补充缺失业务参数，不偷偷改变参数语义，也不在校验失败后走 fallback。
- Tool Definition、参数 Schema 和搜索文档属于同一 Tool 注册生命周期。

### 5. Tool Protocol 与领域边界

- Tool 对外只暴露 definition、args model 与异步 execute。
- execute 接收已经验证的参数对象和不可变 ToolExecutionContext，返回可被统一序列化的业务结果。
- Tool 只能调用 Coaching Application Service；禁止直接访问 SQLAlchemy、Session、Repository 实现或执行 SQL。
- Phase 2 正式业务 Tool 全部是 read-only。`risk` 字段保留 `read_only/mutating` 两级语义，但本阶段不提供或执行 mutating Tool。

### 6. ToolExecutionContext

- ToolExecutionContext 由 Runtime 构造，包含可信的 `user_id`、`thread_id`、`turn_id`、`run_id`、内部 UUID `call_id`、`request_id`、`trace_id` 与统一 `timestamp`。
- 模型只能提供业务参数，不能控制任何身份、所有权、执行归属或链路追踪字段。
- Tool 参数模型不得声明上述可信字段；额外字段校验会拒绝模型尝试注入的身份信息。
- Tool 和 Application Service 的所有用户数据查询必须显式带入 context 中的 `user_id`。

### 7. Registry 与 Provider

- Registry 是唯一注册入口，同时维护 Tool executable、metadata 与搜索索引条目的生命周期。
- 同名注册 fail fast；注销不存在的 Tool 明确失败；不提供静默覆盖。
- Provider 只负责提供一组 Tool。Phase 2 仅实现 System Provider 与 Coaching Provider，不引入 Provider Manager、Catalog Service 或数据库 Catalog。
- Registry 和热注册行为是进程本地状态。多进程部署通过确定性的启动注册获得相同基线，本阶段不提供跨进程动态配置同步。

### 8. Keyword Search

- 使用进程内关键词搜索，不引入 embedding、pgvector、Elasticsearch 或外部搜索服务。
- 检索字段为 Tool name、description、tags 与 search hint；name 权重最高，其次 tags、search hint、description。
- 规范化至少支持英文大小写、ASCII token、Tool name、中文子串或 bigram。
- 单次结果上限为 5，默认返回 3 个。
- `search_tools` 只返回当前仍注册但尚未对该 Session 可见的 Tool，避免结果被 always-on 或已发现能力占满。
- 搜索结果只返回名称、简短描述与相关性信息，不直接绕过 Resolver 执行 Tool。

### 9. Tool Session 与 Discovery

- 每个 AgentRun 创建独立 ToolSession，内部持有 run_id 与 ToolDiscoveryState。
- Discovery 只保存当前 Run 通过 `search_tools` 获得的 Tool 名称，不写 PostgreSQL、Redis 或 Message，也不跨 Turn 复用。
- `search_tools` 是普通可追踪的系统 Tool，但搜索命中后的 discovery 更新由 ToolRuntime 原子完成，AgentRuntime 不理解其内部行为。
- 只有成功返回且仍存在于 Registry 的搜索命中可以加入 discovery；无命中或错误结果不得改变可见集合。
- `search_tools` Observation 中的 `data.hits` 必须与本次成功加入 DiscoveryState 的 Tool 集合完全一致。搜索、Registry 再确认、Discovery mutation 与 Observation 构造是一个不可分割的 Runtime 结果，不允许“向模型报告已命中但实际没有解锁”的部分成功。
- 搜索正常完成但没有匹配 Tool 时仍返回 success Observation，且 `data.hits = []`；零结果不是 `tool_not_found`，也不得改变 DiscoveryState。
- AgentRun 结束后 ToolSession 直接销毁。

### 10. 初始 Tool 策略

- Phase 2 实现与验收基线的 always-on Tool 精确固定为 `search_tools` 与 `get_recent_workouts`。
- 这一选择是本阶段的策略常量，用于验证“高频 Tool 预加载 + 长尾 Tool 动态发现”的组合，不是 Tool Runtime 的永久架构不变量。本 Phase 实现中不得退化成只预加载 `search_tools`，也不得把全部 Tool 设为 always-on。
- 初始 searchable Tool 为 `get_workout_detail`、`get_workout_feedback`、`get_active_goal`、`get_active_plan` 与 `get_latest_athlete_state`。
- always-on 集合未来只能根据 Eval 结果在后续变更中调整，不在 Phase 2 内实现自动策略或配置中心。

### 11. Tool Executor 与错误模型

- ToolExecutor 的固定顺序为：存在性检查 → Session 可用性检查 → 参数验证 → read-only 授权 → timeout → Tool 执行 → 结果归一化。
- timeout 由 Executor 使用每个 Tool Definition 的配置统一控制，不由各 Tool 重复实现。
- Observation 保留 `success/error`，并增加结构化 `error_code`。
- 至少定义 `tool_not_found`、`tool_not_available`、`invalid_arguments`、`tool_timeout` 与 `tool_execution_failed`。
- 预期的应用异常转换为安全错误 Observation；未知异常记录内部结构化日志并只向 Reasoner 返回通用 `tool_execution_failed`。
- Observation 不能包含数据库地址、密钥、内部网络地址、SDK traceback 或基础设施异常原文。
- Tool 级可恢复错误与 Runtime/Protocol 不变量破坏必须分离。`tool_not_found`、`invalid_arguments`、`tool_not_available`、`tool_timeout` 和已经安全归一化的 `tool_execution_failed` 是 Observation，Reasoner 可以继续；Registry 内部状态损坏、ToolSession.run_id 与当前 run_id 不一致、无法建立可信 ToolExecutionContext、Provider 返回完全非法协议等情况必须抛出 typed exception 并使 AgentRun failed。
- Executor 不得用宽泛 `catch Exception → Observation` 吞掉系统不变量错误。只有明确位于 Tool 调用边界内的业务/基础设施执行失败才能归一化为 `tool_execution_failed`。
- AgentRun cancellation 与 Tool timeout 是不同控制流。Tool timeout 返回 `tool_timeout` Observation，允许继续 Reasoning；用户取消 Turn 时 `asyncio.CancelledError` 必须向上传播并立即取消正在执行的 Tool，由 ChatService 持久化 TurnCancelled，绝不能转成 `tool_timeout` 或 `tool_execution_failed`。

### 12. 正式切换 native tool calling

- Phase 2 删除 `response_format=json_object` 与文本 Action Contract，正式使用底层模型 native tool calling。
- Model Request 由 provider-neutral messages 与每轮动态 Model Tool Definitions 组成；Provider Adapter 将其翻译为供应商的 native tools/function calling 协议，并使用自动 Tool 选择语义。
- 当前模型不支持 native tool calling、返回不兼容协议或 Provider 无法提供该能力时必须 fail fast，不得回退到 system prompt 中手写 JSON。
- Native Tool Definition 的 input schema 直接来自 Tool 参数模型。
- Native 对话历史必须按模型协议表达 assistant tool call 与 tool result，不能继续把 ToolCall/Observation 打包成额外 user 文本块。
- 模型返回的 tool-call ID 作为 opaque protocol ID 保存在 ToolCallAction / ReasoningState 中，并在下一次模型请求的 tool result 中原样回传。
- Runtime 同时生成独立 UUID `call_id` 用于 ToolExecutionContext、Lifecycle 与持久化 Trace；协议 ID 与内部 Trace ID 不混用。
- Provider 将 syntactically valid 的参数 JSON 解析成对象，交给 ToolExecutor 做 Schema 校验；无法解析为 JSON 对象的 native 参数属于 typed Reasoner protocol failure。

#### 12.1 Runtime 消息状态模型

- ToolCallAction 至少包含 `type = tool_call`、Tool name、arguments 与非空 `model_call_id`。`model_call_id` 是供应商返回的 opaque protocol ID，Runtime 不解析、不重写、不用它表达内部实体身份。
- Observation 除 source、status、data、error_code 与 error 外，还必须携带与其 ToolCallAction 对应的 `model_call_id`。成功和错误 Observation 都要保留该 ID，使下一次模型请求能够构造合法 tool result。
- ReasoningState 中一次 native Tool 交互的合法顺序固定为“ToolCallAction → 同 model_call_id 的 Observation”。不得出现孤立 Observation、缺少结果的历史 ToolCallAction、ID 不匹配或一个 model_call_id 对应多个结果；违反时属于 Runtime 不变量错误。
- AgentRuntime 在接收 ToolCallAction 后另外生成内部 UUID `call_id`。同一次交互必须保留 `model_call_id ↔ call_id` 映射：前者服务模型协议，后者服务 ToolExecutionContext、Lifecycle 和 RunStep Trace。
- ToolCall RunStep 保存 Tool name、arguments 与 model_call_id；对应 Observation RunStep 保存同一 model_call_id；两条 RunStep 仍通过内部 UUID call_id 关联。

#### 12.2 Provider-neutral ModelMessage

- Provider-neutral 消息层必须能够明确表达 system text、user text、assistant text、assistant tool call 与 tool result 五类消息，不能继续只使用 `role: str + content: str` 覆盖所有形态。
- assistant tool call 消息至少携带 Tool name、arguments 与 model_call_id；tool result 消息至少携带同一个 model_call_id 和序列化后的 Observation。
- PromptRenderer 根据 ContextBundle 与 ReasoningState 还原 native 状态序列：user input → assistant tool call → tool result → 后续 assistant tool call 或 assistant final text。
- Provider Adapter 只负责把这些 provider-neutral 消息翻译为供应商协议，不得把 assistant tool call 或 tool result 序列化进 user/assistant text content 中伪装传递。

### 13. 单 Action 模型响应

- Phase 2 Runtime 采用 Single-Action semantics，每次 Reasoning 只允许一个下一步 Action。这是本阶段 execution policy，不是永久 Agent 架构不变量；未来只有在真实 Eval 证明有收益时才另行设计 parallel tool execution。
- 模型恰好返回一个 Tool Call 时映射为 ToolCallAction；未返回 Tool Call 且文本非空时映射为 FinalAction。
- 同时返回 Tool Call 与附带文本时，以 Tool Call 为当前 Action，附带文本不形成 Canonical Assistant Message。
- 返回多个 Tool Call、空响应或无法归一化的响应时明确失败；Phase 2 不选择第一个后静默忽略其余调用，也不并行执行。

### 14. Context 与 Prompt 边界

- `ContextBundle` 删除静态 capabilities，只保留 system instructions、Working Context、历史 committed Conversation、Memory 接缝与 current input。
- CapabilityContextProvider 与静态 Capability Provider 删除；ContextAssembler 不管理 Tool。
- ReasoningContext 每轮接收稳定 ContextBundle、Run-local ReasoningState 和当前 ToolResolver 结果。
- ReasoningState 只保存 ToolCallAction 与 Observation，不落数据库、不保存隐藏 Chain of Thought、不从 RunStep 恢复驱动正常执行。
- Prompt 只表达教练角色、证据要求和“Tool 不足时使用 search_tools”的行为约束，不包含 Tool Schema、输出 JSON Contract、固定 Workflow 或固定 Tool 顺序。

### 15. 正式 Coaching Tools

- `get_recent_workouts(days)`：读取可信用户最近 1–365 天的 Workout，always-on。
- `get_workout_detail(workout_id)`：使用 `user_id + workout_id` 读取单次 Workout。
- `get_workout_feedback(workout_id)`：读取该 Workout 的 `perceived_exertion`、`subjective_fatigue`、`soreness` 与 `note`；不得把 subjective fatigue 描述成系统推导 Athlete State。
- `get_active_goal()`：读取当前 Active TrainingGoal。
- `get_active_plan()`：读取当前 Active TrainingPlan 与 PlannedSession。
- `get_latest_athlete_state()`：只读取已有 latest AthleteStateSnapshot，不现场计算任何 Athlete State 指标。
- 这些 Tool 复用现有 Coaching Application Service 和 Repository Port，不新增第二套领域查询路径。

#### 15.1 Tool Result Budget

- 所有 Tool Result 必须是受控大小的结构化结果。Tool 是按需调用不代表可以返回全部历史、全部计划课次或无上限文本；每个集合型 Tool 必须在 Application Service/Tool Contract 中定义硬上限，并在达到上限时返回明确的 scope/truncated 元数据。
- `get_active_plan()` 第一版返回 Active Plan 摘要、当前周课次以及从 context timestamp 起未来 14 天内的课次，总课次数不超过 20；不得返回完整十周计划的所有 PlannedSession。
- WorkingContext 中的 active plan 也使用同一受控摘要语义，避免 Tool Observation 已受限但初始 ContextBundle 仍注入完整计划。
- `get_recent_workouts` 保持现有最大记录数边界；detail、feedback、goal 与 athlete state 返回单对象，不附带无界关联集合。
- Tool Result Budget 的截断是显式产品语义，不允许静默丢弃数据；Agent 必须能从结果中知道查询范围和是否被截断。

### 16. Trace、Lifecycle 与 SSE

- 不新增 tool_calls 或 tool_results 表；ToolCall 与 Observation 继续使用现有 RunStep，并通过同一个内部 UUID call_id 关联。
- `search_tools` 自身也写入 tool_call 与 observation RunStep；搜索命中应作为 Observation data 保存，以支持后续 Eval。
- `search_tools` 的 ToolCall RunStep 保存原始 query 与 limit；Observation data 至少使用 `hits` 数组保存每个实际解锁 Tool 的 name、description 与 score。零结果保存空 hits。这样后续 Eval 可以重建搜索 query、命中集合、排名与最终实际调用。
- Lifecycle 正式使用 ToolStarted / ToolCompleted，并继续携带 request_id、trace_id、turn_id、run_id、call_id、tool name、status 与 duration。
- 不新增 ToolDiscovered Lifecycle Event；Discovery 信息以 `search_tools` 的 ToolCall/Observation Trace 为唯一详细记录，ToolStarted/Completed 继续表达执行进度。
- SSE 正式映射为 `tool.started` / `tool.completed`；ToolRuntime 不直接发送 SSE。
- Message 仍只保存 user / assistant Canonical Conversation，Tool Call、Tool Result、搜索记录与模型附带文本都不得写入 Message。

### 17. Persistence 与迁移

- 不创建 tools、tool_registry、tool_search_index、tool_sessions、tool_discoveries、tool_calls 或 tool_results 表。
- Registry 是 process runtime state；Search Index 是 Registry derived state；Discovery 是 AgentRun runtime state；Execution Trace 复用 RunStep。
- 除 RunStep kind 的一次性数据归一化外，Phase 2 不需要新的业务持久化模型。

### 18. 实施顺序

1. 定义 Tool、ToolCallAction、ToolExecutionContext、Observation error code 与 provider-neutral native model contract。
2. 实现 Registry、Provider 注册与 Keyword Search。
3. 实现 ToolSession、DiscoveryState 与 Resolver。
4. 实现统一 ToolExecutor 与错误归一化。
5. 实现 `search_tools` 与六个 read-only Coaching Tools。
6. 让 ReasoningContext、PromptRenderer、LLMReasoner 与 LLM Provider 正式使用动态 native tool calling。
7. 将 AgentRuntime 接入 ToolRuntime，同时保持 ChatService 与 ContextAssembler 所有权不变。
8. 将 Trace、Lifecycle 与 SSE 从 Capability 术语迁移到 Tool。
9. 删除所有旧 Capability 路径并执行必要的数据归一化。
10. 通过集成与场景验收后再宣告 Phase 2 完成。

---

## Testing Decisions

### 测试接缝

主验收只使用一个最高层现有接缝：通过 ChatService 驱动完整 AgentRuntime，并观察最终 ChatResult、Turn/Message/RunStep 持久化状态和 Lifecycle 事件。该接缝覆盖 Context、动态 Tool 可见性、执行、ReasoningState、Trace 与 Transaction B，而不把测试绑定到内部组件组合方式。

Registry、Keyword Search、Resolver 和参数模型属于复杂纯逻辑，允许使用少量窄测试验证确定性不变量。LLM Provider 的 native tool calling 映射位于外部协议边界，使用 fake SDK response 做 Adapter contract test，不调用真实收费模型。

现有 Phase 1 的 `recent training analysis`、`current plan question`、`goal context`、`failed turn`、`cancelled turn`、trusted context、conversation store 与 lifecycle 场景作为回归先例。新测试继续优先断言外部行为、持久化语义和架构边界，不断言私有方法调用顺序。

### 必须通过的场景

1. **Dynamic Tool Discovery Vertical Slice**：初始只可见 `search_tools + get_recent_workouts`；Agent 先读取 recent workouts，再搜索训练详情与主观反馈，下一轮获得两个新 Schema，完成 detail/feedback 调用并基于真实事实形成 FinalAction。
2. **Hidden Tool Guess**：Reasoner 直接猜测 `get_workout_feedback` 时得到 `tool_not_available`；通过 search_tools 发现后，同一 AgentRun 内可以成功执行。
3. **Run-local Isolation**：一个 AgentRun 发现的 Tool 不会出现在下一 AgentRun 的初始可见集合。
4. **Unregister**：Tool 被发现后再注销，下一次 resolve 与 execute 均不可继续使用，Search 也不再返回。
5. **Registry Invariants**：注册后可查询；同名注册 fail fast；注销不存在 Tool 明确失败；Search Index 与 Registry 同步。
6. **Keyword Search**：中文查询、Tool name、tags 与 search hint 能稳定把相关 Tool 放进 Top-K，结果数量不超过 5 且不返回当前已可见 Tool。
7. **Search/Unlock Atomicity**：search_tools Observation 中报告的 hits 与本次加入 DiscoveryState 的集合完全一致；零命中返回 success + empty hits，且不改变 DiscoveryState。
8. **Validation**：缺字段、多字段、错误类型、越界值都返回 `invalid_arguments`，模型 Schema 与 Runtime Validation 由同一参数模型产生。
9. **Trusted Context**：身份字段注入被拒绝；ToolExecutionContext 的 user_id、thread_id、run_id、call_id、request_id、trace_id 与 timestamp 由 Runtime 产生；跨用户 workout/detail/feedback 不可访问。
10. **Timeout, Cancellation And Failure**：Tool 超时返回 `tool_timeout` Observation；Turn cancellation 向上传播并持久化 TurnCancelled；Registry/Session/Context/Provider 协议不变量破坏使 AgentRun failed，不能伪装成 Tool Observation。
11. **Native Tool Calling Contract**：动态 Tool Schema 被传给 Provider；一个 native Tool Call 正确转为带 model_call_id 的 ToolCallAction；对应 Observation 带相同 ID；provider-neutral assistant tool call/tool result 被正确翻译并往返；文本结果转为 FinalAction。
12. **Native Message State**：ReasoningState 只能形成 ToolCallAction → matching Observation 序列；孤立结果、ID 不匹配和缺失结果明确失败；native 消息不得退化为 content JSON。
13. **Invalid Native Response**：多个 Tool Call、空响应和不可解析的 arguments 明确失败，不执行部分结果，不回退文本 JSON Parser。
14. **Trace**：每个 ToolCall 与 Observation 共用内部 UUID call_id；model call ID 与内部 call_id 不混淆；search_tools 的 query、limit、命中、排名与后续实际调用可从 RunStep 重建。
15. **Tool Result Budget**：get_active_plan 只返回规定时间范围和最大课次数，截断信息显式；ContextBundle 不携带完整长期计划；其他集合结果均满足硬上限。
16. **Conversation Boundary**：ToolCall、Observation、搜索记录和模型附带文本不进入 messages；只有 committed user/assistant Message 构成 Canonical Conversation。
17. **Lifecycle And SSE**：事件与流式输出只使用 tool 术语；不新增 ToolDiscovered Event；终态事件、失败边界和提交后 listener 语义继续满足 Phase 1 契约。
18. **Phase 1 Regression**：Conversation 双事务、current input exactly once、失败/取消 Turn、TurnCommitted post-commit 与用户隔离测试全部继续通过。

### Definition of Done

- AgentRuntime 仍保持单 Action 的 Reason–Act–Observe 主循环，且只依赖 ToolRuntime 稳定入口。
- Registry / Search / Discovery / Resolver / Executor 边界清楚，Registered / Visible / Executable 不混淆。
- `search_tools` 与 `get_recent_workouts` 是 Phase 2 实现与验收基线仅有的初始 always-on Tools。
- 动态发现、隐藏 Tool 防绕过、注销失效和 Run-local isolation 场景通过。
- search_tools Observation hits 与实际 Discovery mutation 完全一致，零命中使用 success + empty hits。
- 模型请求正式使用 native tool calling，旧文本 JSON Action Contract 已删除且无 fallback。
- provider-neutral 消息能表达 assistant tool call 与 tool result；native model call ID 与内部 Trace call_id 分工明确并可完整往返。
- Tool 可恢复错误、Runtime 不变量失败、Tool timeout 与 AgentRun cancellation 四类边界有独立测试。
- Tool Result 与 WorkingContext 使用受控摘要，get_active_plan 不返回无界课次集合。
- 参数 Schema 与验证同源，可信 ToolExecutionContext 不受模型控制。
- Trace、Lifecycle、SSE 与代码术语已从 Capability 完整迁移到 Tool。
- SimpleCapabilityExecutor、Capability Ports/Providers/Actions/Events 与所有无用 import、配置和测试已删除。
- 不新增 Tool 持久化表，不引入长期 Memory、MCP 或 mutating workflow。
- Dynamic Tool Discovery Vertical Slice、关键集成/场景测试与全部 Phase 1 回归测试通过。

---

## Out of Scope

- MCP Client / Server 与远程 Tool Provider。
- Semantic Memory、Episodic Memory、Memory Tool 与跨 Turn Tool Discovery Cache。
- Embedding/Vector Tool Search、Elasticsearch、数据库 Tool Catalog 或配置后台。
- Redis Tool Cache、分布式 Registry 热更新和跨进程动态注册同步。
- Athlete State Evaluator、Training Load 算法、Workout Analysis 算法与 Coaching Intelligence。
- Plan Adaptation、Goal 修改、Workout 删除等 mutating Tool。
- Mutating Tool 的 draft、confirmation、approval、commit workflow 与复杂 Policy DSL。
- 多 Tool 并行调用、并发 Tool DAG、批量 Tool Call 与自动选择第一个 Tool Call。
- Weather、Race Search 等真实外部 API。
- Multi-Agent Delegation、长期 Worker 和完整 Eval Runner。
- Tool Search 的跨 Turn LRU、个性化 preload 或基于 Eval 的自动 always-on 策略。
- Phase 2 之后的 parallel tool execution；Single-Action 只作为本阶段 Runtime policy。

---

## Further Notes

- 本 Spec 已正式解决初稿末尾两个待决点：Phase 2 必须切换 native tool calling；初始 always-on Tool 必须是 `search_tools + get_recent_workouts`。
- 上述 always-on 集合是 Phase 2 实现与验收基线，不是永久架构不变量；后续可以依据 Eval 结果通过新决策调整。
- Phase 2 的关键价值是建立稳定的 Tool 接入与治理边界，而不是增加大量业务 Tool。正式业务能力保持为六个 read-only Coaching Tools，足以验证高频预加载与长尾动态发现。
- Phase 1 的 Null MemoryContextProvider 接缝继续保留。未来 Memory Tool 必须作为新的 Tool Provider 接入，不改变 AgentRuntime 与 ToolRuntime 的基本结构。
- Phase 3 Coaching Intelligence 应以 Domain Service + Tool 的方式接入本阶段 Runtime，不把计算逻辑写入 ToolExecutor 或 Prompt。
- Tool Registry 的 crash/restart 语义是由启动 Provider 重新注册确定性基线；本阶段不承诺运行时热注册在多进程之间持久或同步。
- Phase 2 不改变 Phase 1 已接受的 post-commit event crash window，也不引入 Transactional Outbox。
