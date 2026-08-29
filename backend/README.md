# Run Coach Agent — Backend (Phase 2 Completed)

Phase 1–2 已落地：Agent Core 骨架（可信身份、Coaching 领域只读模型、Conversation 双事务、Reason–Act–Observe 循环）与 Dynamic Tool Runtime。下一阶段见 `docs/phases/PHASE_3_COACHING_INTELLIGENCE.md`。

Phase 2 用正式 Dynamic Tool Runtime 替换了临时 Capability 路径：

- **tools/**：Tool Registry（存在性唯一事实来源）、进程内关键词搜索、Run-local Discovery / Resolver / ToolSession、统一 ToolExecutor（存在性 / 可见性 / 参数 / 授权 / 超时 / 错误归一化）
- **初始可见工具**：`search_tools` + `get_recent_workouts`（always-on）；其余五个只读领域工具需经 `search_tools` 发现后才可见与可执行
- **Native tool calling**：模型通过供应商原生工具协议调用（不再有文本 JSON Action Contract）；供应商协议封装在 `infrastructure/llm/provider.py`，Reasoner 只认识统一的 `ToolCallAction` / `Observation` / `FinalAction`

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

场景测试使用 `ScriptedReasoner`，native tool calling 契约测试使用 `FakeProvider`，均不调用真实模型。真实对话需要在 `.env` 中自行配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（需支持 native tool calling）。

## 测试

```bash
pytest
```

## 架构接缝

- `ToolRuntime`（Registry / Search / Resolver / Executor）→ Phase 3 Coaching Intelligence 以 Domain Service + Tool 接入
- `NullMemoryContextProvider` 与未来 Memory Tool → Phase 4 Memory
- `TurnCommitted` → 后续 Projector / Eval
