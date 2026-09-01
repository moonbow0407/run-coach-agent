# Run Coach Agent

面向业余跑者的长期跑步教练 Agent。系统以真实训练事实为依据，维护跑者状态、训练计划与长期记忆，并通过可审计的 Tool Runtime 完成训练分析和计划调整。

## 当前状态

- Phase 1 — Foundation & Agent Core：已实现
- Phase 2 — Dynamic Tool Runtime：已实现
- Phase 3 — Coaching Intelligence：已实现
- Phase 4 — Long-term Memory：已实现
- Phase 5 — Continuous State and Workers：已实现

当前后端回归基线为 `216 passed`（含真实本地 PostgreSQL/Redis 集成测试）。Phase 4/5 的实现说明分别见 [`docs/PHASE_4_IMPLEMENTATION.md`](docs/PHASE_4_IMPLEMENTATION.md) 与 [`docs/PHASE_5_IMPLEMENTATION.md`](docs/PHASE_5_IMPLEMENTATION.md)。

## 已实现能力

- Agent Core：可信用户身份、Conversation 双事务、Reason–Act–Observe 循环、生命周期事件与执行轨迹。
- Dynamic Tool Runtime：Registry、Search、Resolver、Run-local Discovery、统一授权与错误归一化，以及原生 tool calling。
- Coaching Intelligence：训练负荷分析、Athlete State 快照、受约束的计划调整提案，以及确认后生成新计划版本。
- Long-term Memory：Semantic Memory、Episode、Evidence、幂等 Projection、双时间检索、确定性重排和 Context 硬预算。
- Continuous Workers：Transactional Outbox、ARQ/Redis durable tasks、消费 receipt、有限重试/死信、恢复扫描，以及持续 Athlete State / Memory / Episode 投影。
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
├── workers/         # Publisher、Consumer、task handlers、retry 与 recovery
└── infrastructure/  # PostgreSQL、Redis/ARQ、pgvector、LLM、认证与应用装配

frontend/            # Next.js 训练工作台
docs/                # 顶层架构、Phase Contract 与实现说明
```

Canonical Fact、Derived State 与 Memory 的边界以 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 为准。Memory 只保存带正式 Evidence 的派生认知，不复制 Coaching 模块拥有的事实。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐）
- 本地安装的 PostgreSQL（需包含 pgvector 扩展）
- 本地 Redis-compatible server（默认 `localhost:6379`，Worker 必需）
- Node.js 20+ 与 npm（运行前端时需要）

数据库使用本地 PostgreSQL 实例，连接地址默认 `localhost:5432`。

## 快速启动

### 0. 一键启动（推荐）

在项目根目录执行即可拉起完整开发环境。脚本会依次完成目录与命令校验、`.env` 检查、PostgreSQL/Redis 与端口检查、依赖同步、数据库迁移，然后为 API、Worker、前端各开一个独立终端窗口并等待就绪：

```powershell
.\scripts\start.ps1
```

常用参数：`-Mode backend|api|worker|frontend` 只启动部分服务，`-NoDeps` / `-NoMigrate` / `-NoChecks` 跳过对应阶段，`-Seed` 在就绪后写入演示数据。完整说明见脚本头注释，或运行 `Get-Help .\scripts\start.ps1 -Full`。

### 1. 准备数据库

使用本地 PostgreSQL（需已安装 pgvector 扩展）。首次使用时创建应用数据库：

```powershell
psql "postgresql://postgres:<密码>@localhost:5432/postgres" -c "CREATE DATABASE run_coach"
```

### 2. 配置并启动后端

```powershell
Copy-Item .env.example backend\.env
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

另开一个终端启动 durable Worker（同时运行 Outbox Publisher 与 recovery cron）：

```powershell
cd backend
uv run arq app.workers.arq_worker.WorkerSettings
```

编辑 `backend/.env` 时至少需要：

- 将 `DATABASE_URL` 中的 `<密码>` 替换为本机 PostgreSQL 的密码；账号、端口或数据库名与模板默认值（`postgres` / `localhost:5432` / `run_coach`）不同时一并修改；
- 如 Redis 地址或逻辑库不同，修改 `REDIS_URL`；API 可在 Redis 短暂停机时继续提交 canonical state 与 Outbox，恢复后 Worker 会追赶。
- 为 `JWT_SECRET` 设置不少于 32 个字符的随机值；
- 真实对话与 Memory 投影需配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。兼容端点需要支持原生 tool calling 和配置的 embedding 模型。

### 3. 创建演示数据与令牌

在 `backend/` 中执行：

```powershell
uv run python scripts/seed_demo.py
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

完整测试需要支持 pgvector 的本地测试数据库，并要求本机 `localhost:6379` 可连接 Redis（真实 ARQ 场景使用独立逻辑库并在测试后清理）。两个连接串含本机凭据，不写入仓库默认值，必须在运行 pytest 前通过环境变量显式提供；fixture 会用它们自动创建并清理 `run_coach_test`：

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:<密码>@localhost:5432/run_coach_test"
$env:ADMIN_DATABASE_URL = "postgresql+asyncpg://postgres:<密码>@localhost:5432/postgres"
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

## 运维与当前限制

- Redis 数据丢失或 Worker 长时间停机后，可运行 `uv run python scripts/recover_worker_tasks.py` 重新入队缺失 routes；该命令可重复执行。
- 对 dead-letter task 的人工重放必须显式提供原始三元组：`uv run python scripts/replay_worker_task.py --event-id <uuid> --consumer-name <task> --consumer-version 1`；不会创建新 business event。

- PostgreSQL 是 canonical facts、Memory、Outbox 与 consumer receipt 的 source of truth；Redis 仅保存 ARQ operational job state。
- Redis 数据丢失或 Worker 长时间停机后，可运行 `uv run python scripts/recover_worker_tasks.py` 重新入队缺失 routes；该命令可重复执行。
- 当前提供结构化日志与数据库审计状态，尚未实现 dashboard、分布式追踪后端和自动 Outbox 历史清理。
