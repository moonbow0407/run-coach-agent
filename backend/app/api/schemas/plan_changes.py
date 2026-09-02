"""计划调整确认 API 的请求 / 响应模型。"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.coaching.domain.plan.models import PlanChange
from app.coaching.ports.plan_activation_store import PlanActivationResult


class SessionChangeResponse(BaseModel):
    """单节课调整前后的对比。"""

    model_config = ConfigDict(extra="forbid")

    source_session_id: UUID
    scheduled_date: date  # 调整后的上课日期
    from_type: str  # 原课型
    to_type: str  # 新课型
    old_title: str  # 原课次标题
    new_title: str  # 新课次标题
    old_prescription: dict[str, Any]  # 原训练处方（配速 / 距离等参数）
    new_prescription: dict[str, Any]  # 新训练处方


class PlanChangePayloadResponse(BaseModel):
    """提案正文：影响范围与逐课变更。"""

    model_config = ConfigDict(extra="forbid")

    horizon_days: int  # 调整影响的未来天数范围
    changes: list[SessionChangeResponse]  # 逐课变更列表


class PlanChangeResponse(BaseModel):
    """一次计划调整提案的完整视图。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_id: UUID
    from_plan_id: UUID
    from_plan_version: int  # 调整前计划的版本号
    based_on_state_id: UUID
    based_on_state_version: int  # 提案所基于的跑者状态快照版本
    source_turn_id: UUID | None
    source_run_id: UUID | None
    as_of: datetime  # 提案生成的时间点
    change_type: str  # 调整类型
    payload: PlanChangePayloadResponse  # 提案正文（逐课变更）
    reason: str  # 调整理由（面向用户解释）
    status: str  # 提案状态（待确认 / 已确认 / 已拒绝等）
    created_at: datetime  # 提案创建时间
    resolved_at: datetime | None  # 提案解决时间（未解决为空）
    resulting_plan_id: UUID | None


class PlannedSessionResponse(BaseModel):
    """窗口内的一节计划训练课。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    scheduled_date: date  # 计划上课日期
    session_type: str  # 课型（如轻松跑 / 间歇）
    title: str  # 课次标题
    prescription: dict[str, Any]  # 训练处方（配速 / 距离等参数）


class ResultingPlanResponse(BaseModel):
    """确认提案后生成的新计划（含课次）。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int  # 新计划版本号
    status: str  # 计划状态
    starts_on: date  # 计划开始日期
    ends_on: date  # 计划结束日期
    goal_id: UUID | None
    sessions: list[PlannedSessionResponse] = Field(default_factory=list)  # 新计划的训练课列表


class ConfirmPlanChangeResponse(BaseModel):
    """确认提案的响应：提案最新状态 + 可能生成的新计划。"""

    model_config = ConfigDict(extra="forbid")

    plan_change: PlanChangeResponse  # 确认后的提案状态
    resulting_plan_id: UUID | None
    resulting_plan: ResultingPlanResponse | None = None  # 确认生成的新计划详情（可能为空）


def to_plan_change_response(change: PlanChange) -> PlanChangeResponse:
    """领域 PlanChange → 传输 DTO 的唯一映射，查询与确认 / 拒绝共用。"""
    return PlanChangeResponse(
        id=change.id,
        user_id=change.user_id,
        from_plan_id=change.from_plan_id,
        from_plan_version=change.from_plan_version,
        based_on_state_id=change.based_on_state_id,
        based_on_state_version=change.based_on_state_version,
        source_turn_id=change.source_turn_id,
        source_run_id=change.source_run_id,
        as_of=change.as_of,
        change_type=change.change_type.value,
        payload=PlanChangePayloadResponse(
            horizon_days=change.payload.horizon_days,
            changes=[
                SessionChangeResponse(
                    source_session_id=item.source_session_id,
                    scheduled_date=item.scheduled_date,
                    from_type=item.from_type.value,
                    to_type=item.to_type.value,
                    old_title=item.old_title,
                    new_title=item.new_title,
                    old_prescription=item.old_prescription,
                    new_prescription=item.new_prescription,
                )
                for item in change.payload.changes
            ],
        ),
        reason=change.reason,
        status=change.status.value,
        created_at=change.created_at,
        resolved_at=change.resolved_at,
        resulting_plan_id=change.resulting_plan_id,
    )


def to_confirm_plan_change_response(result: PlanActivationResult) -> ConfirmPlanChangeResponse:
    """激活结果 → 确认响应 DTO；未生成新计划时 resulting_plan 留空。"""
    resulting = None
    # 只有真正生成新计划时才组装其详情。
    if result.resulting_plan is not None:
        resulting = ResultingPlanResponse(
            id=result.resulting_plan.id,
            version=result.resulting_plan.version,
            status=result.resulting_plan.status.value,
            starts_on=result.resulting_plan.starts_on,
            ends_on=result.resulting_plan.ends_on,
            goal_id=result.resulting_plan.goal_id,
            sessions=[
                PlannedSessionResponse(
                    id=session.id,
                    scheduled_date=session.scheduled_date,
                    session_type=session.session_type.value,
                    title=session.title,
                    prescription=session.prescription,
                )
                for session in result.resulting_sessions
            ],
        )
    return ConfirmPlanChangeResponse(
        plan_change=to_plan_change_response(result.plan_change),
        resulting_plan_id=result.plan_change.resulting_plan_id,
        resulting_plan=resulting,
    )
