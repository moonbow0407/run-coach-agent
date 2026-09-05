"""场景化演示种子：相对锚点的可编排假数据，Scenario Lab 与 CLI 共用的唯一来源。

ScenarioSpec 用「相对 anchor 的偏移天数」描述一份演示数据，anchor 由调用方传入：
生产/脚本 seed 传墙钟，Scenario Lab 传虚拟时钟——同一份场景描述可在任意"今天"重放。
Workout / Feedback / AthleteState 统一走 Phase 5 canonical mutation + Outbox 路径，
启动 Worker 后即可验证持续投影链路；Goal / Plan 暂无在线 mutation，在短事务中直写。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.application.athlete_recompute_service import AthleteStateRecomputeService
from app.coaching.application.workout_command_service import (
    WorkoutCommandService,
    WorkoutFeedbackCommandService,
)
from app.coaching.domain.workout.models import WorkoutSource, WorkoutType
from app.coaching.ports.workout_mutation_store import (
    WorkoutFeedbackMutation,
    WorkoutMutation,
)
from app.common.clock import Clock
from app.common.errors import NotFoundError
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.agent import (
    AgentRunRow,
    MessageRow,
    RunStepRow,
    ThreadRow,
    TurnRow,
)
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlanChangeRow,
    PlannedSessionRow,
    TrainingGoalRow,
    TrainingPlanRow,
    WorkoutFeedbackRow,
    WorkoutRow,
)
from app.infrastructure.database.models.memory import (
    EpisodeEvidenceRow,
    EpisodeRow,
    MemoryEvidenceRow,
    MemoryProjectionRunRow,
    SemanticMemoryRow,
)
from app.infrastructure.database.models.outbox import EventConsumptionRow, OutboxEventRow
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session


@dataclass(frozen=True)
class PlannedSessionSpec:
    """计划课次：scheduled_date = anchor + days_ahead。"""

    days_ahead: int  # 相对锚点往后的天数
    session_type: WorkoutType  # 课种
    title: str  # 课次标题
    prescription: dict[str, Any]  # 结构化处方（距离/配速等）


@dataclass(frozen=True)
class WorkoutSpec:
    """真实训练：started_at = anchor - days_ago。"""

    days_ago: int  # 相对锚点往前的天数
    workout_type: WorkoutType  # 课种
    duration_s: int  # 时长（秒）
    distance_m: float  # 距离（米）
    avg_heart_rate: int | None = None  # 平均心率
    max_heart_rate: int | None = None  # 最高心率


@dataclass(frozen=True)
class FeedbackSpec:
    """主观反馈：workout_index 指向 ScenarioSpec.workouts 的下标。"""

    workout_index: int  # 反馈针对的训练下标
    perceived_exertion: int | None  # RPE（1–10）
    subjective_fatigue: int | None  # 主观疲劳（1–10）
    soreness: int | None  # 酸痛（1–10）
    note: str | None = None  # 用户备注


@dataclass(frozen=True)
class ScenarioSpec:
    """一份完整演示场景：目标/计划/课次/训练/反馈均为相对 anchor 的偏移。"""

    name: str  # 场景名（API 路径与前端下拉共用）
    description: str  # 一句话说明，面向演示者
    race_days_ahead: int = 45  # 比赛日相对 anchor 的天数
    race_distance_m: int = 21097  # 比赛距离（半马）
    target_time_s: int = 6600  # 目标完赛时间（1h50m）
    plan_start_days_ago: int = 14  # 计划起始日相对 anchor 往前的天数
    plan_days_ahead: int = 56  # 计划结束日相对 anchor 往后的天数
    planned_sessions: tuple[PlannedSessionSpec, ...] = ()
    workouts: tuple[WorkoutSpec, ...] = ()
    feedbacks: tuple[FeedbackSpec, ...] = ()


@dataclass(frozen=True)
class ScenarioSeed:
    """一次场景写入的句柄：新种子与验收逻辑共用的结果字段。"""

    user_id: UUID  # 场景归属用户
    goal_id: UUID  # 备赛目标
    plan_id: UUID  # 当前 active 计划
    workout_ids: tuple[UUID, ...]  # 预置训练
    athlete_state_version: int  # 初始状态快照版本号


# 三堂未来课次是各场景的公共骨架：轻松 / 节奏 / 间歇。
_BASE_PLANNED_SESSIONS = (
    PlannedSessionSpec(
        1, WorkoutType.EASY, "恢复轻松跑", {"distance_m": 7000, "pace": "5:50-6:10"}
    ),
    PlannedSessionSpec(2, WorkoutType.TEMPO, "本周节奏跑", {"distance_m": 9000, "pace": "5:10"}),
    PlannedSessionSpec(4, WorkoutType.INTERVAL, "本周间歇训练", {"reps": 6, "distance_m": 1000}),
)

DEMO_SPEC = ScenarioSpec(
    name="demo",
    description="默认演示：近一周负荷递增 + 最近间歇课高强度反馈",
    planned_sessions=_BASE_PLANNED_SESSIONS,
    workouts=(
        WorkoutSpec(6, WorkoutType.EASY, 2700, 7500.0, 150, 172),
        WorkoutSpec(3, WorkoutType.TEMPO, 3000, 9500.0, 150, 172),
        WorkoutSpec(1, WorkoutType.INTERVAL, 2520, 8000.0, 165, 181),
    ),
    feedbacks=(FeedbackSpec(2, 9, 9, 8, "最后两组间歇明显掉速，今天腿很酸"),),
)

FRESH_SPEC = ScenarioSpec(
    name="fresh",
    description="恢复良好：低强度有氧为主，反馈轻松，无疲劳信号",
    planned_sessions=_BASE_PLANNED_SESSIONS,
    workouts=(
        WorkoutSpec(7, WorkoutType.EASY, 2400, 6000.0, 148, 165),
        WorkoutSpec(4, WorkoutType.EASY, 2700, 6500.0, 150, 168),
        WorkoutSpec(1, WorkoutType.EASY, 3000, 7000.0, 152, 170),
    ),
    feedbacks=(FeedbackSpec(2, 4, 3, 2, "跑完很轻松，状态不错"),),
)

FATIGUE_SPIKE_SPEC = ScenarioSpec(
    name="fatigue_spike",
    description="疲劳激增：连续 6 天负荷爬升，最近间歇课 RPE9 / 疲劳9 / 酸痛8",
    planned_sessions=_BASE_PLANNED_SESSIONS,
    workouts=(
        WorkoutSpec(6, WorkoutType.EASY, 2700, 7500.0, 150, 172),
        WorkoutSpec(5, WorkoutType.EASY, 3000, 8000.0, 152, 174),
        WorkoutSpec(4, WorkoutType.TEMPO, 3000, 9500.0, 160, 176),
        WorkoutSpec(3, WorkoutType.INTERVAL, 2520, 8000.0, 165, 181),
        WorkoutSpec(2, WorkoutType.TEMPO, 3300, 10500.0, 162, 178),
        WorkoutSpec(1, WorkoutType.INTERVAL, 2820, 9000.0, 168, 184),
    ),
    feedbacks=(
        FeedbackSpec(4, 8, 8, 6, "节奏课结束比平时累不少"),
        FeedbackSpec(5, 9, 9, 8, "连着第六天练，最后两组间歇掉速，今天腿很酸"),
    ),
)

MISSED_WEEK_SPEC = ScenarioSpec(
    name="missed_week",
    description="中断一周：最近一次训练在 10 天前，负荷断档",
    planned_sessions=_BASE_PLANNED_SESSIONS,
    workouts=(
        WorkoutSpec(14, WorkoutType.EASY, 2700, 6500.0, 150, 170),
        WorkoutSpec(12, WorkoutType.TEMPO, 3000, 9000.0, 158, 174),
        WorkoutSpec(10, WorkoutType.LONG_RUN, 5400, 12000.0, 155, 175),
    ),
    feedbacks=(FeedbackSpec(2, 6, 5, 4, "长距离最后有点吃力"),),
)

RACE_TAPER_SPEC = ScenarioSpec(
    name="race_taper",
    description="赛前减量：比赛 10 天后，训练量收窄、状态回升",
    race_days_ahead=10,
    planned_sessions=(
        PlannedSessionSpec(1, WorkoutType.EASY, "赛前轻松跑", {"distance_m": 5000, "pace": "6:00"}),
        PlannedSessionSpec(
            3, WorkoutType.TEMPO, "短节奏激活", {"distance_m": 4000, "pace": "5:00"}
        ),
        PlannedSessionSpec(10, WorkoutType.RACE, "半程马拉松比赛", {"distance_m": 21097}),
    ),
    workouts=(
        WorkoutSpec(6, WorkoutType.EASY, 1800, 4000.0, 148, 165),
        WorkoutSpec(4, WorkoutType.EASY, 1500, 3500.0, 146, 162),
        WorkoutSpec(2, WorkoutType.TEMPO, 1500, 4000.0, 155, 172),
    ),
    feedbacks=(FeedbackSpec(2, 5, 4, 3, "腿感轻了，状态在回来"),),
)

# dev 场景 API 与前端下拉共用的注册表；新增场景只需加一份 Spec。
SCENARIOS: dict[str, ScenarioSpec] = {
    DEMO_SPEC.name: DEMO_SPEC,
    FRESH_SPEC.name: FRESH_SPEC,
    FATIGUE_SPIKE_SPEC.name: FATIGUE_SPIKE_SPEC,
    MISSED_WEEK_SPEC.name: MISSED_WEEK_SPEC,
    RACE_TAPER_SPEC.name: RACE_TAPER_SPEC,
}


async def clear_user_coaching_data(session: AsyncSession, *, user_id: UUID) -> None:
    """删除某用户的全部 coaching / 对话 / 记忆数据（保留 users 行，JWT 不失效）。

    顺序按外键依赖从子表到父表；快照必须清空——重算服务以
    max(证据截止线, 最新快照.as_of) 保证单调，不清理则回退后的场景写不进新快照。
    """
    await session.execute(
        delete(RunStepRow).where(
            RunStepRow.run_id.in_(select(AgentRunRow.id).where(AgentRunRow.user_id == user_id))
        )
    )
    await session.execute(delete(AgentRunRow).where(AgentRunRow.user_id == user_id))
    await session.execute(
        delete(MessageRow).where(
            MessageRow.thread_id.in_(select(ThreadRow.id).where(ThreadRow.user_id == user_id))
        )
    )
    await session.execute(delete(TurnRow).where(TurnRow.user_id == user_id))
    await session.execute(delete(ThreadRow).where(ThreadRow.user_id == user_id))
    await session.execute(delete(MemoryEvidenceRow).where(MemoryEvidenceRow.user_id == user_id))
    await session.execute(delete(SemanticMemoryRow).where(SemanticMemoryRow.user_id == user_id))
    await session.execute(delete(EpisodeEvidenceRow).where(EpisodeEvidenceRow.user_id == user_id))
    await session.execute(delete(EpisodeRow).where(EpisodeRow.user_id == user_id))
    await session.execute(
        delete(MemoryProjectionRunRow).where(MemoryProjectionRunRow.user_id == user_id)
    )
    await session.execute(delete(EventConsumptionRow).where(EventConsumptionRow.user_id == user_id))
    await session.execute(delete(OutboxEventRow).where(OutboxEventRow.user_id == user_id))
    await session.execute(delete(PlanChangeRow).where(PlanChangeRow.user_id == user_id))
    await session.execute(delete(WorkoutFeedbackRow).where(WorkoutFeedbackRow.user_id == user_id))
    await session.execute(delete(WorkoutRow).where(WorkoutRow.user_id == user_id))
    await session.execute(
        delete(PlannedSessionRow).where(
            PlannedSessionRow.plan_id.in_(
                select(TrainingPlanRow.id).where(TrainingPlanRow.user_id == user_id)
            )
        )
    )
    await session.execute(delete(TrainingPlanRow).where(TrainingPlanRow.user_id == user_id))
    await session.execute(delete(TrainingGoalRow).where(TrainingGoalRow.user_id == user_id))
    await session.execute(
        delete(AthleteStateSnapshotRow).where(AthleteStateSnapshotRow.user_id == user_id)
    )


async def seed_scenario(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    spec: ScenarioSpec,
    anchor: datetime,
    workout_command_service: WorkoutCommandService,
    workout_feedback_command_service: WorkoutFeedbackCommandService,
    athlete_recompute_service: AthleteStateRecomputeService,
    clock: Clock,
) -> ScenarioSeed:
    """为既有用户写入一份场景数据；目标/计划直写，训练/反馈走 canonical mutation。"""
    goal_id = new_id()
    plan_id = new_id()

    async with short_session(sessions, commit=True) as session:
        # 场景 API 面向已登录用户：用户行必须已存在，缺失直接报错而非静默重建。
        if await session.get(UserRow, user_id) is None:
            raise NotFoundError("scenario_target_user_not_found")
        session.add(
            TrainingGoalRow(
                id=goal_id,
                user_id=user_id,
                goal_type="race",
                race_date=anchor.date() + timedelta(days=spec.race_days_ahead),
                race_distance_m=spec.race_distance_m,
                target_time_s=spec.target_time_s,
                status="active",
                created_at=anchor,
                updated_at=anchor,
            )
        )
        session.add(
            TrainingPlanRow(
                id=plan_id,
                user_id=user_id,
                version=1,
                goal_id=goal_id,
                status="active",
                starts_on=anchor.date() - timedelta(days=spec.plan_start_days_ago),
                ends_on=anchor.date() + timedelta(days=spec.plan_days_ahead),
                created_at=anchor - timedelta(days=spec.plan_start_days_ago),
            )
        )
        await session.flush()
        for planned in spec.planned_sessions:
            session.add(
                PlannedSessionRow(
                    id=new_id(),
                    plan_id=plan_id,
                    scheduled_date=anchor.date() + timedelta(days=planned.days_ahead),
                    session_type=planned.session_type.value,
                    title=planned.title,
                    prescription=planned.prescription,
                )
            )

    workout_ids: list[UUID] = []
    for workout_spec in spec.workouts:
        workout = await workout_command_service.record(
            user_id=user_id,
            mutation=WorkoutMutation(
                started_at=anchor - timedelta(days=workout_spec.days_ago),
                distance_m=workout_spec.distance_m,
                duration_s=workout_spec.duration_s,
                avg_heart_rate=workout_spec.avg_heart_rate,
                max_heart_rate=workout_spec.max_heart_rate,
                workout_type=workout_spec.workout_type,
                source=WorkoutSource.SEED,
            ),
            event_metadata=EventMetadata(correlation_id=new_id()),
        )
        workout_ids.append(workout.id)

    for feedback_spec in spec.feedbacks:
        await workout_feedback_command_service.record(
            user_id=user_id,
            workout_id=workout_ids[feedback_spec.workout_index],
            mutation=WorkoutFeedbackMutation(
                perceived_exertion=feedback_spec.perceived_exertion,
                subjective_fatigue=feedback_spec.subjective_fatigue,
                soreness=feedback_spec.soreness,
                note=feedback_spec.note,
            ),
            event_metadata=EventMetadata(correlation_id=new_id()),
        )

    # 种子完成后同步重算一次：演示打开即是「有状态」的，不必等 Worker 投影。
    snapshot = await athlete_recompute_service.recompute(
        user_id=user_id,
        as_of=clock.now(),
        event_metadata=EventMetadata(correlation_id=new_id()),
    )
    return ScenarioSeed(
        user_id=user_id,
        goal_id=goal_id,
        plan_id=plan_id,
        workout_ids=tuple(workout_ids),
        athlete_state_version=snapshot.version,
    )
