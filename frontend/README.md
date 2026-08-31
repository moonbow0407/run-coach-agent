# 训练台 · run-coach-agent 前端

面向业余跑者的跑步教练工作台：目标与状态快照、本周课表（含教练调整提案的确认）、与教练对话（SSE 实时轨迹）、最近训练与主观反馈。

视觉方向是「清晨训练台」：冷雾灰绿底、沥青墨、跑道红作为唯一强调色（只用于需要用户决定的事）。

## 技术栈

Next.js 15（App Router）+ React 19 + TypeScript + Tailwind CSS v4。字体：Archivo（可变字宽，标题与大数字）、IBM Plex Mono（数据）、中文回退系统字体。

## 启动

前端通过 Next.js rewrites 把 `/api/v1` 与 `/health` 代理到 FastAPI，**后端无需配置 CORS**。后端地址默认 `http://localhost:8000`，可用环境变量 `BACKEND_ORIGIN` 覆盖。

```bash
# 1. 后端（本地 PostgreSQL 需已启动并安装 pgvector）
cd backend
cp ../.env.example .env                  # 填写 JWT_SECRET（≥32 字符）与 LLM_* 配置
alembic upgrade head                     # 建表
uvicorn app.main:app --reload            # 默认 8000 端口

# 2. 演示数据与令牌
python scripts/seed_vertical_slice.py    # 输出 user_id
python scripts/issue_token.py <user_id>  # 输出 JWT

# 3. 前端
cd ../frontend
npm install
npm run dev                              # http://localhost:3000
```

首次打开是「连接你的教练」页面：粘贴上一步签发的令牌（由 `issue_token.py` 生成本地 JWT，本仓库没有登录 API）。令牌存于浏览器 localStorage，「断开」即清除。

## 页面结构

- **页头**：训练目标（比赛倒计时）+ 系统推导的状态快照（疲劳/恢复/周负荷/完成率/证据截至/评估版本）——快照可解释、可追溯。
- **课表侧栏（签名元素）**：本周课表负荷剖面条；教练的调整提案以红铅笔批注画在课次上，在这里「采纳调整」或「保持原计划」。
- **对话**：与教练对话；Agent 调用的每个工具以轨迹行展示（工具名 + 耗时），回复正文在 Turn 提交后到达。
- **最近训练**：客观事实列表；展开行显示该次训练的主观反馈（RPE / 疲劳 / 酸痛 / 备注），懒加载。

## 依赖的后端接口

| 方法 | 路径 |
| --- | --- |
| POST | `/api/v1/chat/stream`（SSE） |
| GET | `/api/v1/threads/{thread_id}/messages` |
| GET | `/api/v1/goals/active` |
| GET | `/api/v1/plans/active` |
| GET | `/api/v1/athlete-state/latest` |
| GET | `/api/v1/workouts?days=30` |
| GET | `/api/v1/workouts/{workout_id}/feedback` |
| GET | `/api/v1/plan-changes/pending` |
| GET/POST | `/api/v1/plan-changes/{id}`、`/confirm`、`/reject` |

SSE 事件口径见 `backend/app/api/sse.py`：`run.started / reasoning.started / tool.started / tool.completed / response.delta / run.completed / run.failed / run.cancelled`。注意 `response.delta` 是 Turn 提交后一次性发出的完整正文，不是逐 token 流。
