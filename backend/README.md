# Run Coach Agent — Backend

FastAPI 后端已实现 Phase 1–5：Agent Core、Dynamic Tool Runtime、Coaching Intelligence、Long-term Memory 与 Continuous Workers。完整项目说明和前端启动方式见仓库根目录 [`README.md`](../README.md)。

## 技术栈

- Python 3.12+
- FastAPI、Pydantic、SQLAlchemy Async、Alembic
- PostgreSQL（含 pgvector 扩展）
- Redis + ARQ（durable task operational state）
- OpenAI-compatible LLM / embedding provider
- pytest、pytest-asyncio、Ruff

## 启动

使用本地 PostgreSQL（需已安装 pgvector 扩展），复制配置：

```powershell
Copy-Item .env.example backend\.env
```

复制配置后，按需修改 `backend/.env` 中的 `DATABASE_URL`（默认连接 `localhost:5432` 的本地实例）和 `REDIS_URL`（默认 `localhost:6379/0`），并填写不少于 32 个字符的 `JWT_SECRET`。应用数据库 `run_coach` 需提前创建，Redis-compatible server 需已启动。

随后在 `backend/` 执行：

```powershell
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

另开终端启动 Worker：

```powershell
uv run arq app.workers.arq_worker.WorkerSettings
```

真实对话与 Memory Projection 还需要配置 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`；场景测试使用测试 Reasoner，不调用真实模型。

## 演示数据与访问令牌

```powershell
uv run python scripts/seed_demo.py
uv run python scripts/issue_token.py <user_id>
```

健康检查地址为 `http://127.0.0.1:8000/health`，API 使用 `/api/v1` 前缀并要求 Bearer JWT。

## 验证

```powershell
uv run ruff check app tests

$env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:<密码>@localhost:5432/run_coach_test"
$env:ADMIN_DATABASE_URL = "postgresql+asyncpg://postgres:<密码>@localhost:5432/postgres"
uv run pytest -q
```

测试默认使用同一本地实例上的 `run_coach_test` 数据库，fixture 会自动创建和清理；真实 ARQ 场景还连接本机 Redis 的隔离逻辑库并在结束后清理。本地 PostgreSQL 必须已安装 pgvector 扩展。

## 模块边界

- `app/agent`：Agent Runtime、Conversation、Context 与 Reasoner。
- `app/coaching`：训练事实、状态计算、训练分析和计划调整。
- `app/memory`：Semantic Memory、Episode、Evidence、Projection、Lifecycle 与 Retrieval。
- `app/tools`：Registry、Discovery、Resolver 与 Executor。
- `app/workers`：durable event routing、Publisher、Consumer、四个 task handlers、retry/dead-letter 与 recovery。
- `app/infrastructure`：数据库、Redis/ARQ、pgvector、LLM、认证和 production wiring。

Production business owner 已切换到 durable Worker，不再装配 Phase 3/4 的同步 PlanChange/Memory listener。手工恢复缺失任务可运行：

```powershell
uv run python scripts/recover_worker_tasks.py
```

人工重放必须显式指定原始 event 与 route 三元组（只重放已存在的 dead-letter receipt）：

```powershell
uv run python scripts/replay_worker_task.py --event-id <uuid> --consumer-name <task> --consumer-version 1
```
