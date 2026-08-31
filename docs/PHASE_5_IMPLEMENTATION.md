# Phase 5 实现说明

> 对应合同：`docs/phases/PHASE_5_CONTINUOUS_STATE_AND_WORKERS.md`

## 交付范围

Phase 5 已把 Workout / Feedback / Conversation terminal / Plan activation 的 canonical mutation 与 durable event 写入收敛到同一 PostgreSQL transaction，并以 PostgreSQL Outbox、Redis/ARQ、durable consumer receipt 驱动持续 Athlete State、Semantic Memory 与 Episode。

Production business owner 已从 Phase 3/4 的进程内 listener 切换到 Worker；`LifecycleDispatcher` 继续只服务 runtime lifecycle、SSE、日志与 trace。

## Durable event v1

固定支持七个 schema：

| event type | aggregate | task routes |
| --- | --- | --- |
| `conversation.turn_committed.v1` | Conversation Turn | `finalize_terminal_turn.v1`、`project_semantic_memory.v1` |
| `conversation.turn_failed.v1` | Conversation Turn | `finalize_terminal_turn.v1` |
| `conversation.turn_cancelled.v1` | Conversation Turn | `finalize_terminal_turn.v1` |
| `coaching.workout_changed.v1` | Workout | `recompute_athlete_state.v1` |
| `coaching.workout_feedback_changed.v1` | WorkoutFeedback | `recompute_athlete_state.v1` |
| `coaching.athlete_state_recomputed.v1` | AthleteStateSnapshot | `project_episode.v1` |
| `coaching.plan_change_confirmed.v1` | PlanChange | `project_episode.v1` |

Envelope 只包含稳定 identity、可信 `user_id`、event time、严格 versioned payload 与 correlation / causation / trace metadata，不携带 Message 文本、Memory 内容或 queue provider 类型。

ARQ job id 固定为：

```text
<task_name>:<task_version>:<event_id>
```

重复 enqueue 和 Redis recovery 不创建新的 business event identity。

## Transaction 与并发边界

- Conversation Transaction B 在同一 transaction 写 assistant Message、Turn / AgentRun terminal state 与 terminal event。
- `WorkoutCommandService` / `WorkoutFeedbackCommandService` 是正式写入口；canonical row 与 event 共用同一个 `updated_at / available_at`。
- `PlanActivationStore.confirm()` 在用户行锁下激活 Plan N+1、确认 PlanChange 并写 `PlanChangeConfirmed`；重复 confirm 不写第二个 event。
- Athlete State 重算使用 `AthleteStateRecomputeUnitOfWork`：`UserRow FOR UPDATE` 覆盖 evidence read、availability cutoff、deterministic evaluator、Snapshot append 与 `AthleteStateRecomputed` event。
- 较旧 trigger 或已覆盖 cutoff 返回 `OBSOLETE_NOOP`，不追加旧 Snapshot；不使用 Redis distributed lock。

## Worker 与 Episode 取证

四个 task handler 只解码 event identity 并调用正式 Application Service：

- terminal Turn 收尾 PlanChange Draft；
- Workout / Feedback 触发 Athlete State 重算；
- committed Turn 触发 Semantic Memory；
- State / confirmed PlanChange 触发 Episode。

`EpisodeProjectionService.project_trigger()` 以 28 天有界窗口查询 canonical evidence candidates，并在 Application Service 内选择稳定 fatigue anchor、PlanChange 的 canonical `based_on_state_id` 与首个 recovery outcome。Task payload 不能指定 Episode type、时间窗或 evidence ids。

## Retry、dead-letter 与恢复

- Consumer transient failure 使用 5 秒至 6 小时的确定性 bounded backoff（最多 8 次 receipt attempt）。
- permanent / poison / canonical ownership failure 进入 PostgreSQL `event_consumptions.dead_lettered`；未知 schema 在 Publisher 阶段进入 `outbox_events.quarantined`。
- Publisher claim 与 Redis enqueue 之间不持有数据库 transaction；enqueue 后崩溃允许重复 deterministic job。
- ARQ Worker 自带 Outbox Publisher cron 与 recovery cron。
- Redis 丢失或 Worker 长时间停机后可重复运行：

```powershell
cd backend
uv run python scripts/recover_worker_tasks.py
```

恢复扫描只对超过安全窗口、已 `PUBLISHED` 且 required route 尚无 completed/dead-letter receipt 的 event 使用原 identity 重新入队。

dead-letter 只能通过显式 route 三元组重放，命令为：

```powershell
uv run python scripts/replay_worker_task.py --event-id <uuid> --consumer-name <task> --consumer-version 1
```
畸形 pending Outbox 行在 claim 阶段逐行转为 `QUARANTINED`，不会阻塞同一批的合法 event。

## 启动与部署切换

```powershell
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

另开终端：

```powershell
uv run arq app.workers.arq_worker.WorkerSettings
```

部署时先 migration，再启动 Redis 与 Worker，最后启用 producers。回滚时先停 producers / Worker；PostgreSQL Outbox 与 receipt 必须保留到确认无需恢复后。历史 canonical rows 不伪造为“刚发生”的 event。

## Acceptance evidence

七类合同场景的当前证据：

1. Transaction / Outbox atomicity：`test_conversation_store.py`、`test_workout_mutations.py`、`test_plan_change_persistence.py`。
2. Duplicate delivery / one logical result：`test_arq_delivery.py`、`test_memory_vertical_slice.py`、`test_athlete_state_snapshots.py`。
3. Transient retry / permanent quarantine：真实 Redis `test_arq_delivery.py` 与 PostgreSQL `test_outbox_quarantine.py`。
4. Trustworthy Athlete State time：`test_continuous_state_worker.py`，包含晚导入历史 Workout 与 obsolete trigger。
5. Continuous Memory / Episode：`test_memory_vertical_slice.py` 与 `test_episode_trigger_projection.py`，覆盖 PlanChange + later recovery 原位完成。
6. Downtime / crash recovery：真实 Redis `test_arq_delivery.py`，覆盖 enqueue 后崩溃恢复与 service commit 后 receipt 未完成重试。
7. Same-user concurrency / cross-user isolation：`test_continuous_state_worker.py` 与既有 Memory / Plan / State user isolation 回归。

Focused tests 覆盖严格 event codec/routing、retry 上界、SQLAlchemy 数据库异常分类：`tests/unit/test_worker_contracts.py`、`tests/unit/test_worker_failure_classification.py`；真实 PostgreSQL 回归还覆盖恢复饥饿、poison quarantine 与显式 replay。

## 已知限制

- Phase 5 只提供结构化日志和 PostgreSQL 审计状态，未实现 dashboard、distributed tracing backend 或复杂指标平台。
- Outbox 历史清理与 dead-letter 管理 UI 留给 production hardening；当前不自动删除已发布事件。
- Memory extractor / embedding 仍需要真实 LLM provider 配置；缺少配置属于 permanent worker failure，不写零向量或伪造成功。
- Redis 需由本地/生产环境按 AOF、no-eviction 和容量要求运维，本仓库不再提供 Docker PostgreSQL/Redis 编排。
