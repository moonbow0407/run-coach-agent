"""PlanActivationStore：在一个事务内完成经过领域校验的计划版本激活。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.coaching.contracts.durable_events import (
    PlanChangeConfirmedV1,
    new_plan_change_confirmed_event,
)
from app.coaching.domain.plan.models import PlanChangeStatus, PlanStatus
from app.coaching.domain.plan.validator import validate_plan_change_activation
from app.coaching.ports.plan_activation_store import PlanActivationResult
from app.common.errors import ConflictError, DomainError, NotFoundError
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.locking import lock_user_row
from app.infrastructure.database.mappers import (
    athlete_state_from_row,
    plan_change_from_row,
    plan_from_row,
    session_from_row,
)
from app.infrastructure.database.models.coaching import (
    AthleteStateSnapshotRow,
    PlanChangeRow,
    PlannedSessionRow,
    TrainingPlanRow,
)
from app.infrastructure.outbox.writer import OutboxWriter


class SqlAlchemyPlanActivationStore:
    """计划激活仓储：确认提案 = 生成新版本计划并替换课次的事务实现。"""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
    ) -> None:
        self._sessions = sessions
        self._outbox = outbox

    async def confirm(
        self,
        *,
        user_id: UUID,
        plan_change_id: UUID,
        now: datetime,
        event_metadata: EventMetadata,
    ) -> PlanActivationResult:
        # 不能用 short_session(commit=True)：标 STALE 后仍要抛 ConflictError，
        # 必须先 COMMIT 再抛，否则 rollback 会丢掉 STALE。
        async with self._sessions() as session:
            try:
                await lock_user_row(session, user_id)
                change_row = await session.scalar(
                    select(PlanChangeRow).where(
                        PlanChangeRow.id == plan_change_id,
                        PlanChangeRow.user_id == user_id,
                    )
                )
                if change_row is None:
                    raise NotFoundError("计划调整不存在")
                plan_change = plan_change_from_row(change_row)
                if plan_change.status is PlanChangeStatus.CONFIRMED:
                    # 幂等：重复确认直接返回既有结果，不再生成新计划
                    resulting = await _load_plan_with_sessions(
                        session, user_id=user_id, plan_id=plan_change.resulting_plan_id
                    )
                    await session.commit()
                    return PlanActivationResult(
                        plan_change=plan_change,
                        resulting_plan=resulting[0] if resulting else None,
                        resulting_sessions=resulting[1] if resulting else (),
                        already_confirmed=True,
                    )
                if plan_change.status is not PlanChangeStatus.PENDING_CONFIRMATION:
                    raise DomainError("plan_change_not_pending")

                active_row = await session.scalar(
                    select(TrainingPlanRow).where(
                        TrainingPlanRow.user_id == user_id,
                        TrainingPlanRow.status == PlanStatus.ACTIVE.value,
                    )
                )
                latest_state_row = await session.scalar(
                    select(AthleteStateSnapshotRow)
                    .where(AthleteStateSnapshotRow.user_id == user_id)
                    .order_by(AthleteStateSnapshotRow.version.desc())
                    .limit(1)
                )
                if active_row is None or latest_state_row is None:
                    # 前置事实（active 计划/状态快照）已消失：提案作废为 STALE
                    change_row.status = PlanChangeStatus.STALE.value
                    change_row.resolved_at = now
                    await session.commit()
                    raise ConflictError("stale", code="stale")

                active_plan = plan_from_row(active_row)
                latest_state = athlete_state_from_row(latest_state_row)
                fresh = (
                    active_plan.id == plan_change.from_plan_id
                    and active_plan.version == plan_change.from_plan_version
                    and latest_state.id == plan_change.based_on_state_id
                    and latest_state.version == plan_change.based_on_state_version
                )
                if not fresh:
                    # 当前 active 计划/快照与提案依据的版本不一致：提案已过时
                    change_row.status = PlanChangeStatus.STALE.value
                    change_row.resolved_at = now
                    await session.commit()
                    raise ConflictError("stale", code="stale")

                session_rows = (
                    await session.scalars(
                        select(PlannedSessionRow)
                        .where(PlannedSessionRow.plan_id == active_plan.id)
                        .order_by(PlannedSessionRow.scheduled_date.asc())
                    )
                ).all()
                base_sessions = [session_from_row(row) for row in session_rows]
                validate_plan_change_activation(
                    user_id=user_id,
                    plan_change=plan_change,
                    active_plan=active_plan,
                    latest_state=latest_state,
                    base_sessions=base_sessions,
                )

                replacements = {
                    change.source_session_id: change for change in plan_change.payload.changes
                }
                new_plan_id = new_id()
                new_plan_row = TrainingPlanRow(
                    id=new_plan_id,
                    user_id=user_id,
                    version=active_plan.version + 1,
                    goal_id=active_plan.goal_id,
                    status=PlanStatus.ACTIVE.value,
                    starts_on=active_plan.starts_on,
                    ends_on=active_plan.ends_on,
                    created_at=now,
                )
                # 先退出旧 Active，再插入新 Active，避免部分唯一约束冲突。
                active_row.status = PlanStatus.SUPERSEDED.value
                await session.flush()
                session.add(new_plan_row)
                await session.flush()

                new_session_rows: list[PlannedSessionRow] = []
                for old in session_rows:
                    replacement = replacements.get(old.id)
                    if replacement is None:
                        # 未被替换的课次：原样复制进新计划版本
                        new_session_rows.append(
                            PlannedSessionRow(
                                id=new_id(),
                                plan_id=new_plan_id,
                                scheduled_date=old.scheduled_date,
                                session_type=old.session_type,
                                title=old.title,
                                prescription=dict(old.prescription or {}),
                            )
                        )
                    else:
                        # 被替换的课次：采用提案中的目标课型 / 标题 / 处方
                        new_session_rows.append(
                            PlannedSessionRow(
                                id=new_id(),
                                plan_id=new_plan_id,
                                scheduled_date=replacement.scheduled_date,
                                session_type=replacement.to_type.value,
                                title=replacement.new_title,
                                prescription=dict(replacement.new_prescription),
                            )
                        )
                session.add_all(new_session_rows)
                await session.flush()
                change_row.status = PlanChangeStatus.CONFIRMED.value
                change_row.resolved_at = now
                change_row.resulting_plan_id = new_plan_id
                self._outbox.add(
                    session,
                    new_plan_change_confirmed_event(
                        user_id=user_id,
                        payload=PlanChangeConfirmedV1(
                            plan_change_id=change_row.id,
                            from_plan_id=change_row.from_plan_id,
                            resulting_plan_id=new_plan_id,
                            based_on_state_id=change_row.based_on_state_id,
                            confirmed_at=now,
                        ),
                        metadata=event_metadata,
                    ),
                )
                await session.commit()
                confirmed = plan_change_from_row(change_row)
                return PlanActivationResult(
                    plan_change=confirmed,
                    resulting_plan=plan_from_row(new_plan_row),
                    resulting_sessions=tuple(session_from_row(row) for row in new_session_rows),
                    already_confirmed=False,
                )
            except ConflictError:
                raise  # STALE 已先提交落库，这里只把冲突继续抛给上层
            except Exception:
                await session.rollback()  # 其他异常整体回滚，不留半成品
                raise


async def _load_plan_with_sessions(
    session: AsyncSession,
    *,
    user_id: UUID,
    plan_id: UUID | None,
) -> tuple | None:
    """加载指定计划及其课次；计划不存在或未指定时返回 None。"""
    if plan_id is None:
        return None
    plan_row = await session.scalar(
        select(TrainingPlanRow).where(
            TrainingPlanRow.id == plan_id,
            TrainingPlanRow.user_id == user_id,
        )
    )
    if plan_row is None:
        return None
    session_rows = (
        await session.scalars(
            select(PlannedSessionRow)
            .where(PlannedSessionRow.plan_id == plan_id)
            .order_by(PlannedSessionRow.scheduled_date.asc())
        )
    ).all()
    return plan_from_row(plan_row), tuple(session_from_row(row) for row in session_rows)
