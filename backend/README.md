# Run Coach Agent — Backend (Phase 1)

Phase 1 建立 Agent Core 运行骨架：可信身份、Coaching 领域只读模型、Conversation 双事务、Reason–Act–Observe 循环。

## 要求

- Python 3.12+
- Docker（PostgreSQL 16）

## 启动

在仓库根目录：

```bash
docker compose up -d postgres
# 容器映射到本机 5433，避免与已有 PostgreSQL 抢 5432
```

在 `backend/`：

```bash
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
copy ..\.env.example .env
# 编辑 .env，为 JWT_SECRET 填写至少 32 个字符的随机值
alembic upgrade head
uvicorn app.main:app --reload
```

本地签发测试 token（先 seed 用户）：

```bash
python scripts/seed_vertical_slice.py
python scripts/issue_token.py <user_id>
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat ^
  -H "Authorization: Bearer <token>" ^
  -H "Content-Type: application/json" ^
  -d "{\"message\":\"我最近训练状态怎么样？\"}"
```

场景测试使用 `ScriptedReasoner`，不调用真实模型。真实对话需要在 `.env` 中自行配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。

## 测试

```bash
pytest
```

## 架构接缝

- `CapabilityExecutor` → Phase 2 Tool Runtime
- `NullMemoryContextProvider` → Phase 4 Memory
- `TurnCommitted` → 后续 Projector / Eval
