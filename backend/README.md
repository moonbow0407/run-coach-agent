# Run Coach Agent — Backend

FastAPI 后端已实现 Phase 1–4：Agent Core、Dynamic Tool Runtime、Coaching Intelligence 与 Long-term Memory。完整项目说明和前端启动方式见仓库根目录 [`README.md`](../README.md)。

## 技术栈

- Python 3.12+
- FastAPI、Pydantic、SQLAlchemy Async、Alembic
- PostgreSQL 16 + pgvector
- OpenAI-compatible LLM / embedding provider
- pytest、pytest-asyncio、Ruff

## 启动

先在仓库根目录启动数据库：

```powershell
docker compose up -d postgres
Copy-Item .env.example backend\.env
```

容器绑定 `127.0.0.2:5433`。复制配置后，应把 `backend/.env` 中的 `DATABASE_URL` 主机改为 `127.0.0.2`，并填写不少于 32 个字符的 `JWT_SECRET`。

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

$env:TEST_DATABASE_URL = "postgresql+asyncpg://run_coach:run_coach@127.0.0.2:5433/run_coach_test"
$env:ADMIN_DATABASE_URL = "postgresql+asyncpg://run_coach:run_coach@127.0.0.2:5433/postgres"
uv run pytest -q
```

测试 fixture 会创建和清理 `run_coach_test`，数据库必须已安装 pgvector 扩展。

## 模块边界

- `app/agent`：Agent Runtime、Conversation、Context 与 Reasoner。
- `app/coaching`：训练事实、状态计算、训练分析和计划调整。
- `app/memory`：Semantic Memory、Episode、Evidence、Projection、Lifecycle 与 Retrieval。
- `app/tools`：Registry、Discovery、Resolver 与 Executor。
- `app/infrastructure`：数据库、pgvector、LLM、认证和 production wiring。

生产路径使用真实 `RetrievedMemoryContextProvider`。Phase 4 的进程内 Memory listener 仍是 best-effort owner；可靠 Outbox / Worker 投递由 Phase 5 实现。
