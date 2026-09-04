"""Eval Fixture 种子实现：全部使用合成数据与正式写入路径。

规则（PHASE 6 §10）：
- 静态历史（训练 / 计划 / 状态快照）可直接插入，与 Phase 1 seed builder 同口径；
- 长期记忆必须通过正式 Projection（合法 Evidence + 真实 embedding）产生；
- 所有业务时间冻结在明确的带时区时间；每个 Case / Trial 独立用户。
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from app.bootstrap import AppContainer
from app.common.ids import new_id
from app.evals.environment import EvalClock
from app.identity.application.request_context import RequestContext
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlannedSessionRow,
    TrainingGoalRow,
    TrainingPlanRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from app.infrastructure.evals.readers import EvalMemoryStateReader
from app.infrastructure.seed.vertical_slice import seed_vertical_slice
from app.memory.application.episode_projection_service import EpisodeProjectionService
from app.memory.domain.episode import EpisodeType
from app.memory.domain.evidence import EvidenceSourceType

# 全部 fixture 的业务时间基准：早于任何 Case 的 as_of / turn 时间。
SEED_BASE = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


async def _seed_user(session, now: datetime) -> UUID:
    """创建独立用户：每个 Case / Trial 的数据都归属独立 user_id。"""
    user_id = new_id()
    session.add(UserRow(id=user_id, created_at=now, updated_at=now))
    await session.flush()
    return user_id


async def _seed_goal_and_plan(
    session,
    *,
    user_id: UUID,
    now: datetime,
    sessions: list[tuple[date, str, str, dict[str, object]]],
) -> tuple[UUID, UUID]:
    """创建半马目标 + v1 生效计划及课次，返回 (goal_id, plan_id)。"""
    goal_id = new_id()
    session.add(
        TrainingGoalRow(
            id=goal_id,
            user_id=user_id,
            goal_type="race",
            race_date=date(2026, 10, 18),
            race_distance_m=21097,
            target_time_s=6600,
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    plan_id = new_id()
    session.add(
        TrainingPlanRow(
            id=plan_id,
            user_id=user_id,
            version=1,
            goal_id=goal_id,
            status="active",
            starts_on=date(2026, 7, 20),
            ends_on=date(2026, 9, 27),
            created_at=now - timedelta(days=30),
        )
    )
    await session.flush()
    for scheduled_date, session_type, title, prescription in sessions:
        session.add(
            PlannedSessionRow(
                id=new_id(),
                plan_id=plan_id,
                scheduled_date=scheduled_date,
                session_type=session_type,
                title=title,
                prescription=prescription,
            )
        )
    await session.flush()
    return goal_id, plan_id


async def _seed_workout(
    session,
    *,
    user_id: UUID,
    started_at: datetime,
    distance_m: float,
    duration_s: int,
    avg_hr: int,
    max_hr: int,
    workout_type: str,
) -> UUID:
    """插入一条静态历史训练记录。"""
    workout_id = new_id()
    session.add(
        WorkoutRow(
            id=workout_id,
            user_id=user_id,
            started_at=started_at,
            distance_m=distance_m,
            duration_s=duration_s,
            avg_heart_rate=avg_hr,
            max_heart_rate=max_hr,
            workout_type=workout_type,
            source="eval-seed",
            created_at=started_at,
            updated_at=started_at,
        )
    )
    await session.flush()
    return workout_id


async def _seed_snapshot(
    session,
    *,
    user_id: UUID,
    version: int,
    as_of: datetime,
    fatigue: str,
    recovery: str,
    load: float,
) -> UUID:
    """插入一份静态历史状态快照，返回快照 ID。"""
    snapshot_id = new_id()
    session.add(
        AthleteStateSnapshotRow(
            id=snapshot_id,
            user_id=user_id,
            version=version,
            as_of=as_of,
            fatigue_level=fatigue,
            recovery_level=recovery,
            recent_training_load=load,
            workout_completion_rate=0.9,
            training_load_coverage=1.0,
            signals=[],
            confidence=0.9,
            algorithm_version="eval-seed",
            created_at=as_of,
        )
    )
    await session.flush()
    return snapshot_id


# ---- runner_vertical_slice：高疲劳 + 跑崩的间歇 + 未来窗口有质量课 ----


async def seed_runner_vertical_slice(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """复用 Phase 1 垂直切片 builder，但快照为 HIGH 疲劳（降负荷 v1 前提）。"""
    async with short_session(container.sessions, commit=True) as session:
        seed = await seed_vertical_slice(session, fatigue_level="high")
    return seed.user_id, {
        "goal_id": seed.goal_id,
        "plan_id": seed.plan_id,
        "interval_workout_id": seed.workout_ids[-1],
        "state_snapshot_id": seed.athlete_state_snapshot_id,
    }


# ---- runner_normal_fatigue：正常训练 + 轻微疲劳（不应触发计划调整）----


async def seed_runner_normal_fatigue(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """低疲劳、恢复良好的正常训练场景：未来窗口含节奏课，考验模型不滥触发。"""
    async with short_session(container.sessions, commit=True) as session:
        user_id = await _seed_user(session, SEED_BASE)
        goal_id, plan_id = await _seed_goal_and_plan(
            session,
            user_id=user_id,
            now=SEED_BASE,
            sessions=[
                (date(2026, 8, 29), "easy", "第 6 周轻松跑", {"distance_m": 8000}),
                (
                    date(2026, 8, 31),
                    "tempo",
                    "第 6 周节奏跑",
                    {"distance_m": 10000, "pace": "5:10"},
                ),
            ],
        )
        last = await _seed_workout(
            session,
            user_id=user_id,
            started_at=datetime(2026, 8, 24, 7, 0, tzinfo=UTC),
            distance_m=8000.0,
            duration_s=2760,
            avg_hr=138,
            max_hr=152,
            workout_type="easy",
        )
        session.add(
            WorkoutFeedbackRow(
                id=new_id(),
                user_id=user_id,
                workout_id=last,
                perceived_exertion=3,
                subjective_fatigue=2,
                soreness=1,
                note="强度不大，跑完很轻松",
                created_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
                updated_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
            )
        )
        snapshot_id = await _seed_snapshot(
            session,
            user_id=user_id,
            version=1,
            as_of=datetime(2026, 8, 27, 23, 59, tzinfo=UTC),
            fatigue="low",
            recovery="good",
            load=28.0,
        )
    return user_id, {"goal_id": goal_id, "plan_id": plan_id, "state_snapshot_id": snapshot_id}


# ---- runner_without_state：缺少可信 Athlete State ----


async def seed_runner_without_state(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """有目标与计划但没有任何状态快照：状态证据不足，不允许提案。"""
    async with short_session(container.sessions, commit=True) as session:
        user_id = await _seed_user(session, SEED_BASE)
        goal_id, plan_id = await _seed_goal_and_plan(
            session,
            user_id=user_id,
            now=SEED_BASE,
            sessions=[
                (date(2026, 8, 29), "easy", "第 6 周轻松跑", {"distance_m": 8000}),
                (
                    date(2026, 8, 31),
                    "tempo",
                    "第 6 周节奏跑",
                    {"distance_m": 10000, "pace": "5:10"},
                ),
            ],
        )
        await _seed_workout(
            session,
            user_id=user_id,
            started_at=datetime(2026, 8, 24, 7, 0, tzinfo=UTC),
            distance_m=8000.0,
            duration_s=2760,
            avg_hr=140,
            max_hr=155,
            workout_type="easy",
        )
    return user_id, {"goal_id": goal_id, "plan_id": plan_id}


# ---- semantic_memory_distractors：目标可用时间约束 + 11 条干扰记忆 ----


async def seed_semantic_memory_distractors(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """通过正式对话投影路径播种 12 条语义记忆；alias 在 drain 后解析。"""
    from app.evals.fixtures import AVAILABILITY_DISTRACTOR_INPUTS

    async with short_session(container.sessions, commit=True) as session:
        user_id = await _seed_user(session, SEED_BASE)
    thread_id: UUID | None = None
    for index, content in enumerate(AVAILABILITY_DISTRACTOR_INPUTS):
        moment = SEED_BASE + timedelta(hours=index)
        clock.advance_to(moment)
        result = await container.chat_service.send_message(
            request_context=RequestContext(
                user_id=user_id,
                request_id=uuid4(),
                trace_id=uuid4(),
                timestamp=moment,
            ),
            thread_id=thread_id,
            content=content,
        )
        thread_id = result.thread_id
    return user_id, {}


# ---- fatigue_episode_history：1 条完成的疲劳恢复 Episode + 4 条干扰 ----


async def seed_fatigue_episode_history(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """用真实 embedding 与正式 Episode 投影播种 5 条情景记忆；required 为最近完成的。"""
    clock.advance_to(datetime(2026, 8, 28, 6, 0, tzinfo=UTC))
    async with short_session(container.sessions, commit=True) as session:
        user_id = await _seed_user(session, clock.now())
        may = await _seed_snapshot(
            session,
            user_id=user_id,
            version=1,
            as_of=datetime(2026, 5, 10, 22, 0, tzinfo=UTC),
            fatigue="high",
            recovery="poor",
            load=88.0,
        )
        june = await _seed_snapshot(
            session,
            user_id=user_id,
            version=2,
            as_of=datetime(2026, 6, 15, 22, 0, tzinfo=UTC),
            fatigue="moderate",
            recovery="fair",
            load=64.0,
        )
        july = await _seed_snapshot(
            session,
            user_id=user_id,
            version=3,
            as_of=datetime(2026, 7, 8, 22, 0, tzinfo=UTC),
            fatigue="moderate",
            recovery="fair",
            load=70.0,
        )
        early_aug = await _seed_snapshot(
            session,
            user_id=user_id,
            version=4,
            as_of=datetime(2026, 8, 2, 22, 0, tzinfo=UTC),
            fatigue="moderate",
            recovery="fair",
            load=66.0,
        )
        trigger = await _seed_snapshot(
            session,
            user_id=user_id,
            version=5,
            as_of=datetime(2026, 8, 10, 22, 0, tzinfo=UTC),
            fatigue="high",
            recovery="poor",
            load=92.0,
        )
        outcome = await _seed_snapshot(
            session,
            user_id=user_id,
            version=6,
            as_of=datetime(2026, 8, 18, 22, 0, tzinfo=UTC),
            fatigue="low",
            recovery="good",
            load=52.0,
        )
    service: EpisodeProjectionService = container.episode_projection_service
    version = container.settings.memory_projector_version
    required = await service.project_window(
        user_id=user_id,
        type=EpisodeType.FATIGUE_AND_RECOVERY,
        started_at=datetime(2026, 8, 10, 22, 0, tzinfo=UTC),
        ended_at=datetime(2026, 8, 18, 22, 0, tzinfo=UTC),
        source_ids=(
            (EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, trigger),
            (EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, outcome),
        ),
        projector_version=version,
    )
    for snapshot_id, start, end in (
        (
            may,
            datetime(2026, 5, 10, 22, 0, tzinfo=UTC),
            datetime(2026, 5, 20, 22, 0, tzinfo=UTC),
        ),
        (
            june,
            datetime(2026, 6, 15, 22, 0, tzinfo=UTC),
            datetime(2026, 6, 25, 22, 0, tzinfo=UTC),
        ),
        (
            july,
            datetime(2026, 7, 8, 22, 0, tzinfo=UTC),
            datetime(2026, 7, 18, 22, 0, tzinfo=UTC),
        ),
        (
            early_aug,
            datetime(2026, 8, 2, 22, 0, tzinfo=UTC),
            datetime(2026, 8, 6, 22, 0, tzinfo=UTC),
        ),
    ):
        await service.project_window(
            user_id=user_id,
            type=EpisodeType.FATIGUE_AND_RECOVERY,
            started_at=start,
            ended_at=end,
            source_ids=((EvidenceSourceType.ATHLETE_STATE_SNAPSHOT, snapshot_id),),
            projector_version=version,
        )
    if not required.result_ids:
        raise RuntimeError("episode_seed_missing_required_result")
    return user_id, {"fatigue_recovery_august": required.result_ids[0]}


# ---- 两个纠正 fixture：只建用户；记忆由 Runner 执行 Case turns 后解析 ----


async def seed_schedule_preference_correction(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """作息偏好纠正场景：先晚上、后早上的两次显式表达由 Case turns 提供。"""
    async with short_session(container.sessions, commit=True) as session:
        user_id = await _seed_user(session, SEED_BASE)
    return user_id, {}


async def seed_training_frequency_correction(
    container: AppContainer, clock: EvalClock
) -> tuple[UUID, dict[str, UUID]]:
    """每周频率纠正场景：3 次 → 5 次的两次显式表达由 Case turns 提供。"""
    async with short_session(container.sessions, commit=True) as session:
        user_id = await _seed_user(session, SEED_BASE)
    return user_id, {}


# ---- drain 后的 alias 解析 ----


async def resolve_availability_distractor_ids(
    container: AppContainer, user_id: UUID
) -> dict[str, UUID]:
    """按 subject_key 把已投影的语义记忆解析为 alias → UUID（每键唯一）。"""
    return await _resolve_by_subject_keys(
        container,
        user_id,
        subject_key_to_alias={
            rule.subject_key: rule.alias for rule in _availability_rules()
        },
    )


async def resolve_schedule_correction_ids(
    container: AppContainer, user_id: UUID
) -> dict[str, UUID]:
    """作息纠正：旧=evening，新=morning（同 subject_key 下的两次断言）。"""
    states = await EvalMemoryStateReader(container.sessions).list_semantic_memories(
        user_id=user_id
    )
    ids: dict[str, UUID] = {}
    for state in states:
        if state.subject_key != "preferred_training_time":
            continue
        if state.value == "evening":
            ids["schedule_evening"] = state.id
        elif state.value == "morning":
            ids["schedule_morning"] = state.id
    return ids


async def resolve_training_frequency_ids(
    container: AppContainer, user_id: UUID
) -> dict[str, UUID]:
    """频率纠正：旧=3 次，新=5 次。"""
    states = await EvalMemoryStateReader(container.sessions).list_semantic_memories(
        user_id=user_id
    )
    ids: dict[str, UUID] = {}
    for state in states:
        if state.subject_key != "weekly:training:frequency":
            continue
        if state.value == 3:
            ids["frequency_three"] = state.id
        elif state.value == 5:
            ids["frequency_five"] = state.id
    return ids


async def _resolve_by_subject_keys(
    container: AppContainer,
    user_id: UUID,
    *,
    subject_key_to_alias: dict[str, str],
) -> dict[str, UUID]:
    states = await EvalMemoryStateReader(container.sessions).list_semantic_memories(
        user_id=user_id
    )
    ids: dict[str, UUID] = {}
    for state in states:
        alias = subject_key_to_alias.get(state.subject_key)
        if alias is not None:
            ids[alias] = state.id
    return ids


def _availability_rules():
    """从抽取器规则表取干扰 fixture 的规则（延迟导入避免循环依赖）。"""
    from app.evals.fixtures.extractors import AVAILABILITY_DISTRACTOR_RULES

    return AVAILABILITY_DISTRACTOR_RULES
