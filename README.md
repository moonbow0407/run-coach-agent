# Run Coach Agent

面向业余跑者的长期跑步教练 Agent。系统以真实训练事实为依据，维护跑者状态、训练计划与长期记忆，并通过可审计的 Tool Runtime 完成训练分析和计划调整。

## 当前状态

- Phase 1 — Foundation & Agent Core：已实现
- Phase 2 — Dynamic Tool Runtime：已实现
- Phase 3 — Coaching Intelligence：已实现
- Phase 4 — Long-term Memory：已实现
- Phase 5 — Continuous State and Workers：设计草案，尚未实现

当前回归基线为 `198 passed`。Phase 4 的实现与已知限制见 [`docs/PHASE_4_IMPLEMENTATION.md`](docs/PHASE_4_IMPLEMENTATION.md)。

## 已实现能力

- Agent Core：可信用户身份、Conversation 双事务、Reason–Act–Observe 循环、生命周期事件与执行轨迹。
- Dynamic Tool Runtime：Registry、Search、Resolver、Run-local Discovery、统一授权与错误归一化，以及原生 tool calling。
- Coaching Intelligence：训练负荷分析、Athlete State 快照、受约束的计划调整提案，以及确认后生成新计划版本。
- Long-term Memory：Semantic Memory、Episode、Evidence、幂等 Projection、双时间检索、确定性重排和 Context 硬预算。
- 训练工作台：目标、状态、周计划、计划调整确认、最近训练与 SSE 对话界面。

## 架构

仓库采用模块化单体：

```text
backend/app/
├── agent/           # Agent Runtime、Context、Reasoner 与 Conversation
├── coaching/        # Workout、Goal、Plan、Athlete State 与训练分析
├── memory/          # Semantic Memory、Episode、Evidence、Projection 与 Retrieval
├── tools/           # Tool Registry、Discovery、Resolver 与 Executor
├── identity/        # 用户身份与请求上下文
└── infrastructure/  # PostgreSQL、pgvector、LLM、认证与应用装配

frontend/            # Next.js 训练工作台
docs/                # 顶层架构、Phase Contract 与实现说明
```

Canonical Fact、Derived State 与 Memory 的边界以 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 为准。Memory 只保存带正式 Evidence 的派生认知，不复制 Coaching 模块拥有的事实。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐）
- Docker / Docker Compose
- Node.js 20+ 与 npm（运行前端时需要）

数据库使用 PostgreSQL 16 + pgvector。仓库容器绑定 `127.0.0.2:5433`，避免与本机 PostgreSQL 冲突。

## 快速启动

### 1. 启动数据库

```powershell
docker compose up -d postgres
```

### 2. 配置并启动后端

```powershell
Copy-Item .env.example backend\.env
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

编辑 `backend/.env` 时至少需要：

- 将 Docker 数据库地址设为 `postgresql+asyncpg://run_coach:run_coach@127.0.0.2:5433/run_coach`；
- 为 `JWT_SECRET` 设置不少于 32 个字符的随机值；
- 真实对话与 Memory 投影需配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。兼容端点需要支持原生 tool calling 和配置的 embedding 模型。

### 3. 创建演示数据与令牌

在 `backend/` 中执行：

```powershell
uv run python scripts/seed_vertical_slice.py
uv run python scripts/issue_token.py <user_id>
```

### 4. 启动前端

```powershell
cd ..\frontend
npm install
npm run dev
```

打开 `http://localhost:3000`，粘贴上一步生成的 JWT。前端会把 `/api/v1` 与 `/health` 代理到默认的 `http://localhost:8000`。

## 验证

后端静态检查：

```powershell
cd backend
uv run ruff check app tests
```

完整测试需要支持 pgvector 的独立测试数据库：

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://run_coach:run_coach@127.0.0.2:5433/run_coach_test"
$env:ADMIN_DATABASE_URL = "postgresql+asyncpg://run_coach:run_coach@127.0.0.2:5433/postgres"
uv run pytest -q
```

前端验证：

```powershell
cd frontend
npm run typecheck
npm run build
```

测试中的 Agent 场景使用 `ScriptedReasoner` 或 Fake Provider，不调用真实模型。

## 文档

- [顶层架构](docs/ARCHITECTURE.md)
- [Phase 1 — Foundation & Agent Core](docs/phases/PHASE_1_FOUNDATION_AGENT_CORE.md)
- [Phase 2 — Dynamic Tool Runtime](docs/phases/PHASE_2_DYNAMIC_TOOL_RUNTIME.md)
- [Phase 3 — Coaching Intelligence](docs/phases/PHASE_3_COACHING_INTELLIGENCE.md)
- [Phase 4 — Long-term Memory](docs/phases/PHASE_4_LONG_TERM_MEMORY.md)
- [Phase 5 — Continuous State and Workers](docs/phases/PHASE_5_CONTINUOUS_STATE_AND_WORKERS.md)

## 当前限制

Phase 4 通过进程内 `TurnCommitted` listener 以 best-effort 方式触发 Memory Projection，因此仍存在数据库提交成功、但进程在投影完成前退出的交付窗口。Projection 本身可安全幂等重放；Phase 5 将通过 Transactional Outbox、Queue 与 Worker 消除该窗口。
