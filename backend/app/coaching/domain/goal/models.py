"""Goal 领域模型：跑者的训练目标（比赛目标或一般目标）。"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum  # StrEnum：成员值即字符串，可直接序列化存储
from uuid import UUID


class GoalType(StrEnum):
    RACE = "race"  # 比赛目标：有明确比赛日期、距离与目标成绩
    GENERAL = "general"  # 一般目标：无比赛，只为保持或提升跑步能力


class GoalStatus(StrEnum):
    ACTIVE = "active"  # 生效中：系统据此提供教练建议
    COMPLETED = "completed"  # 已完赛或目标达成（终态）
    CANCELLED = "cancelled"  # 用户主动放弃（终态）


@dataclass(frozen=True)  # 不可变数据类：领域对象创建后不允许原地修改
class TrainingGoal:
    id: UUID
    user_id: UUID  # 归属用户，仓储层必须按此隔离数据
    goal_type: GoalType  # 目标类型，决定 race_* 字段是否有值
    race_date: date | None  # 比赛日期；一般目标为 None
    race_distance_m: int | None  # 比赛距离（米）；一般目标为 None
    target_time_s: int | None  # 目标完赛时间（秒）；无成绩要求为 None
    status: GoalStatus  # 生命周期状态：生效 / 完结 / 取消
    created_at: datetime
    updated_at: datetime
