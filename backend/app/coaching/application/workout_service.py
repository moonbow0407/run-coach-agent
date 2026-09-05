"""训练记录查询服务：Agent 能力读取训练事实的领域入口。"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.coaching.domain.workout.models import Workout, WorkoutFeedback
from app.coaching.ports.workout_repository import WorkoutRepository
from app.common.clock import Clock
from app.common.errors import DomainError

# 单次返回的训练记录硬上限：达到即视为可能截断，
# 由调用方作为 Tool Result Budget 元数据（truncated）显式报告。
RECENT_WORKOUTS_LIMIT = 50

# 热上下文注入：最近反馈摘要条数与备注截断长度。
RECENT_FEEDBACK_SUMMARY_LIMIT = 5
RECENT_FEEDBACK_SUMMARY_DAYS = 14
_NOTE_SNIPPET_MAX = 80


@dataclass(frozen=True)
class FeedbackSummary:
    """轻量反馈摘要：日期 + RPE + 备注片段，供 WorkingContext 注入。"""

    workout_id: UUID
    started_on: date  # 训练日历日
    perceived_exertion: int | None  # 用力程度（RPE）
    subjective_fatigue: int | None  # 主观疲劳
    note_snippet: str | None  # 截断后的备注


class WorkoutQueryService:
    """训练记录与训练反馈的查询服务。入参校验在这里做，仓储只负责取数。"""

    def __init__(self, repository: WorkoutRepository, clock: Clock) -> None:
        self._repository = repository
        # clock 用于计算“最近 N 天”的时间窗口，测试可注入固定时钟。
        self._clock = clock

    async def get_recent_workouts(self, *, user_id: UUID, days: int) -> list[Workout]:
        """查询用户最近 N 天的训练记录（含上限，防止一次拉取过多）。"""
        if days <= 0:
            raise DomainError("days 必须为正整数")
        since = self._clock.now() - timedelta(days=days)
        return await self._repository.list_recent(
            user_id=user_id, since=since, limit=RECENT_WORKOUTS_LIMIT
        )

    async def get_workout(self, *, user_id: UUID, workout_id: UUID) -> Workout | None:
        """按 id 读取单条训练；不存在或不属于该用户返回 None。"""
        return await self._repository.get(user_id=user_id, workout_id=workout_id)

    async def get_feedback(
        self,
        *,
        user_id: UUID,
        workout_id: UUID,
    ) -> WorkoutFeedback | None:
        """读取某次训练的用户反馈；尚未报告返回 None。"""
        return await self._repository.get_feedback(user_id=user_id, workout_id=workout_id)

    async def list_recent_feedback(self, *, user_id: UUID, days: int) -> list[WorkoutFeedback]:
        """查询用户最近 N 天训练上的反馈（按 created_at 升序）。"""
        if days <= 0:
            raise DomainError("days 必须为正整数")
        since = self._clock.now() - timedelta(days=days)
        workouts = await self._repository.list_recent(
            user_id=user_id, since=since, limit=RECENT_WORKOUTS_LIMIT
        )
        if not workouts:
            return []
        return await self._repository.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=[item.id for item in workouts],
            end=self._clock.now(),
        )

    async def list_recent_feedback_summaries(
        self,
        *,
        user_id: UUID,
        days: int = RECENT_FEEDBACK_SUMMARY_DAYS,
        limit: int = RECENT_FEEDBACK_SUMMARY_LIMIT,
    ) -> list[FeedbackSummary]:
        """最近反馈摘要（按训练开始时间倒序，最多 limit 条）。"""
        if days <= 0:
            raise DomainError("days 必须为正整数")
        if limit <= 0:
            raise DomainError("limit 必须为正整数")
        since = self._clock.now() - timedelta(days=days)
        workouts = await self._repository.list_recent(
            user_id=user_id, since=since, limit=RECENT_WORKOUTS_LIMIT
        )
        if not workouts:
            return []
        by_id = {item.id: item for item in workouts}
        feedbacks = await self._repository.list_feedback_for_workouts(
            user_id=user_id,
            workout_ids=list(by_id.keys()),
            end=self._clock.now(),
        )
        # 同一课次多条反馈时取最新一条（list 按 created_at 升序）。
        latest_by_workout: dict[UUID, WorkoutFeedback] = {}
        for item in feedbacks:
            latest_by_workout[item.workout_id] = item
        summaries: list[FeedbackSummary] = []
        for workout_id, feedback in latest_by_workout.items():
            workout = by_id.get(workout_id)
            if workout is None:
                continue
            note = feedback.note.strip() if feedback.note else None
            if note and len(note) > _NOTE_SNIPPET_MAX:
                note = note[:_NOTE_SNIPPET_MAX].rstrip() + "…"
            summaries.append(
                FeedbackSummary(
                    workout_id=workout_id,
                    started_on=workout.started_at.date(),
                    perceived_exertion=feedback.perceived_exertion,
                    subjective_fatigue=feedback.subjective_fatigue,
                    note_snippet=note,
                )
            )
        summaries.sort(key=lambda item: item.started_on, reverse=True)
        return summaries[:limit]
