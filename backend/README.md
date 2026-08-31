# Run Coach Agent — Backend

FastAPI 后端已实现 Phase 1–4：Agent Core、Dynamic Tool Runtime、Coaching Intelligence 与 Long-term Memory。完整项目说明和前端启动方式见仓库根目录 [`README.md`](../README.md)。

## 技术栈

- Python 3.12+
- FastAPI、Pydantic、SQLAlchemy Async、Alembic
- PostgreSQL（含 pgvector 扩展）
- OpenAI-compatible LLM / embedding provider
- pytest、pytest-asyncio、Ruff

## 启动

使用本地 PostgreSQL（需已安装 pgvector 扩展），复制配置：

```powershell
Copy-Item .env.example backend\.env
```

复制配置后，按需修改 `backend/.env` 中的 `DATABASE_URL`（默认连接 `localhost:5432` 的本地实例），并填写不少于 32 个字符的 `JWT_SECRET`。应用数据库 `run_coach` 需提前创建。

随后在 `backend/` 执行：

```powershell
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

真实对话与 Memory Projection 还需要配置 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`；场景测试使用测试 Reasoner，不调用真实模型。

## 演示数据与访问令牌

```powershell
uv run python scripts/seed_vertical_slice.py
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

测试默认使用同一本地实例上的 `run_coach_test` 数据库，fixture 会自动创建和清理，本机实例连接信息不同时才需要上面的环境变量覆盖。本地 PostgreSQL 必须已安装 pgvector 扩展。

## 模块边界

- `app/agent`：Agent Runtime、Conversation、Context 与 Reasoner。
- `app/coaching`：训练事实、状态计算、训练分析和计划调整。
- `app/memory`：Semantic Memory、Episode、Evidence、Projection、Lifecycle 与 Retrieval。
- `app/tools`：Registry、Discovery、Resolver 与 Executor。
- `app/infrastructure`：数据库、pgvector、LLM、认证和 production wiring。

生产路径使用真实 `RetrievedMemoryContextProvider`。Phase 4 的进程内 Memory listener 仍是 best-effort owner；可靠 Outbox / Worker 投递由 Phase 5 实现。
