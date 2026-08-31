# Phase 4 Implementation Notes

## Runtime ownership

- `memory` 模块拥有 Semantic Memory、Episode、Evidence、Projection、Lifecycle 与 Retrieval。
- Agent Runtime、ContextAssembler 和 Tool Runtime 只读取受预算约束的 Memory View，不写 Memory。
- Phase 4 production owner 是进程内 `MemoryProjectionLifecycleListener`。它只消费
  `TurnCommitted`，并在提交后 best-effort 调用 `SemanticMemoryProjectionService`。
- failed / cancelled Turn 不进入投影。Phase 5 会用 Outbox + Worker 替换这个临时 owner。

## Versions and persistence

- migration：`0004_phase4_long_term_memory.py`
- semantic projector：`phase4.v1`
- retrieval policy：`phase4.v1`
- embedding dimensions：`1536`
- embedding model / version：由 `MEMORY_EMBEDDING_MODEL` 与
  `MEMORY_EMBEDDING_VERSION` 配置，并保存在每条 Memory / Episode 上。
- PostgreSQL + pgvector 是唯一长期 Memory store；数据库为本地安装的
  PostgreSQL 实例（需包含 pgvector 扩展）。

## Idempotency and replay

- committed conversation projection key：`turn:<turn_id>`
- inferred projection key：`inferred:<type>:<sorted-source-identity-hash>`
- plan episode key：`plan_change:<plan_change_id>`
- fatigue episode key：`fatigue_trigger:<trigger_snapshot_id>`
- receipt、Memory / Episode、Evidence 与 supersession 在同一用户行锁短事务提交。
- 手动重放调用相同 Application Service 与 source identity；相同 fingerprint 返回原结果。
- Episode 新增 outcome 会更新同一 logical row；较旧 source 子集迟到返回 obsolete no-op。

## Failure and current limitation

- extractor / embedding / pgvector 失败会抛 typed failure，不返回空列表或零向量伪装成功。
- 没有候选是合法 completed projection receipt。
- 当前仍存在 `DB COMMIT → process crash / listener failure → projection delayed` 窗口。
  运维可按 committed `turn_id` 手动重放；可靠交付由 Phase 5 负责。

## Verification

测试数据库必须支持 pgvector，使用本地 PostgreSQL 实例。验证命令：

```powershell
cd backend
uv sync --extra dev
uv run ruff check app tests
uv run pytest
```

Phase 4 acceptance 覆盖 committed Turn vertical slice、失败 Turn 排除、重放幂等、
explicit correction 与历史 `as_of`、相同向量跨用户隔离、Episode
BUILDING → COMPLETED / obsolete delivery，以及 inferred 独立证据晋升与 Context 硬预算。
