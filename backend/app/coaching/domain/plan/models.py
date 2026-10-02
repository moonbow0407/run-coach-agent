"""Plan 领域模型：版本化训练计划、计划课次与计划调整提案。"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum  # StrEnum：成员值即字符串，可直接序列化存储
from typing import Any
from uuid import UUID


class PlanStatus(StrEnum):
    ACTIVE = "active"  # 当前生效版本
    SUPERSEDED = "superseded"  # 已被更新版本取代
    COMPLETED = "completed"  # 计划执行完毕
    CANCELLED = "cancelled"  # 计划被取消


class PlanChangeStatus(StrEnum):
    DRAFT = "draft"  # Agent 本轮生成的草案，用户还看不到
    PENDING_CONFIRMATION = "pending_confirmation"  # Turn 提交后等待用户确认
    CONFIRMED = "confirmed"  # 用户确认，已激活为新计划版本（终态）
    REJECTED = "rejected"  # 用户拒绝（终态）
    STALE = "stale"  # 确认时依据的计划 / 状态版本已过期（终态）
    ABANDONED = "abandoned"  # 所在 Turn 未提交，草案作废（终态）


class PlanChangeType(StrEnum):
    # v1 唯一支持的调整类型：降低未来窗口的训练负荷。
    REDUCE_UPCOMING_LOAD = "reduce_upcoming_load"


class SessionType(StrEnum):
    EASY = "easy"  # 轻松跑课次
    TEMPO = "tempo"  # 节奏跑课次
    INTERVAL = "interval"  # 间歇课次
    LONG_RUN = "long_run"  # 长距离课次
    REST = "rest"  # 休息日
    RACE = "race"  # 比赛日：激活校验禁止改动
    OTHER = "other"  # 其他未分类


@dataclass(frozen=True)
class TrainingPlan:
    """版本化的训练计划：调整必须生成新版本（Plan Version N+1），不覆盖历史。"""

    id: UUID  # 版本实例 id：每个计划版本各自拥有独立 id
    user_id: UUID  # 归属用户，仓储层必须按此隔离数据
    version: int  # 递增版本号：确认激活时用于新鲜度校验
    goal_id: UUID | None  # 关联的 Goal；无目标计划为 None
    status: PlanStatus  # 生命周期状态（生效 / 被取代 / 完成 / 取消）
    starts_on: date  # 计划开始日期（含）
    ends_on: date  # 计划结束日期（含）
    created_at: datetime  # 该版本的创建时间


@dataclass(frozen=True)
class PlannedSession:
    """计划中的单次训练课次；prescription 为结构化处方（距离 / 配速等）。"""

    id: UUID
    plan_id: UUID  # 所属计划版本
    scheduled_date: date  # 计划训练日期
    session_type: SessionType  # 课型
    title: str  # 课次标题，展示给用户
    prescription: dict[str, Any]  # 结构化处方（距离 / 配速等），由计划生成方写入


@dataclass(frozen=True)
class SessionChange:
    """PlanChange payload 中的单次课次替换。由领域服务生成，不由模型提供。"""

    source_session_id: UUID  # 被替换的原课次 id
    scheduled_date: date  # 原课次日期（激活校验要求与源一致）
    from_type: SessionType  # 原课型（校验用）
    to_type: SessionType  # 目标课型（v1 只允许 REST）
    old_title: str  # 原标题（校验用，防止提案基于过期数据）
    new_title: str  # 替换后的标题
    old_prescription: dict[str, Any]  # 原处方（校验用）
    new_prescription: dict[str, Any]  # 新处方（改为 REST 时为空）


@dataclass(frozen=True)
class PlanChangePayload:
    """结构化 Diff：horizon 与课次替换列表。"""

    horizon_days: int  # 调整作用天数：as_of 次日起的未来窗口长度
    changes: tuple[SessionChange, ...]  # 窗口内的课次替换列表


@dataclass(frozen=True)
class PlanChange:
    """一次计划调整提案。DRAFT 不等于已激活的 Active Plan。"""

    id: UUID
    user_id: UUID  # 归属用户，仓储层必须按此隔离数据
    from_plan_id: UUID  # 基于哪个计划版本提出的调整
    from_plan_version: int  # 提案时的计划版本号，确认时用于新鲜度校验
    based_on_state_id: UUID  # 基于哪份跑者状态快照
    based_on_state_version: int  # 提案时的快照版本号，确认时用于新鲜度校验
    source_turn_id: UUID | None  # 产生本提案的对话轮次（Turn）
    source_run_id: UUID | None  # 产生本提案的 Agent 推理运行（Run）
    as_of: datetime  # 提案基准时间，决定调整窗口
    change_type: PlanChangeType  # 调整类型（v1 仅降负荷）
    payload: PlanChangePayload  # 结构化课次 diff
    reason: str  # 面向用户的调整理由
    status: PlanChangeStatus  # 生命周期状态
    created_at: datetime  # 提案创建时间
    resolved_at: datetime | None  # 进入终态的时间；未解决为 None
    resulting_plan_id: UUID | None  # 确认激活后生成的新计划 id
