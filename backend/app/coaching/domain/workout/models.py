"""Workout 领域模型：训练事实与用户主观反馈的原始记录。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum  # StrEnum：成员值即字符串，可直接序列化存储
from uuid import UUID

from app.common.errors import DomainError


class WorkoutType(StrEnum):
    EASY = "easy"  # 轻松跑
    TEMPO = "tempo"  # 节奏跑（乳酸门槛强度）
    INTERVAL = "interval"  # 间歇跑
    LONG_RUN = "long_run"  # 长距离拉练
    REST = "rest"  # 休息日
    RACE = "race"  # 比赛
    OTHER = "other"  # 其他未分类


class WorkoutSource(StrEnum):
    SEED = "seed"  # 系统种子数据（历史导入），非用户操作产生
    MANUAL = "manual"  # 用户通过对话或接口手动记录


def validate_subjective_scale(name: str, value: int | None) -> int | None:
    """主观量表统一为 1–10。None 表示用户未报告该项。"""
    if value is None:
        return None
    if not 1 <= value <= 10:
        # 量表越界属于非法输入，尽早失败而不是静默截断。
        raise DomainError(f"{name} 必须是 1–10 的整数")
    return value


@dataclass(frozen=True)  # 不可变数据类：训练事实一旦记录不原地修改
class Workout:
    id: UUID
    user_id: UUID  # 归属用户，仓储层必须按此隔离数据
    started_at: datetime  # 训练开始时间：负荷归属于哪一天以此为准
    distance_m: float | None  # 距离（米）；未记录为 None
    duration_s: int | None  # 时长（秒）；sRPE 负荷计算的必备项之一
    avg_heart_rate: int | None  # 平均心率（次/分）
    max_heart_rate: int | None  # 最高心率（次/分）
    workout_type: WorkoutType  # 课型；只作分类信号，不当生理负荷系数
    source: WorkoutSource  # 数据来源（种子导入 / 手动记录）
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkoutFeedback:
    """用户报告的原始主观事实，不等于 AthleteStateSnapshot 中的系统推导状态。"""

    id: UUID
    user_id: UUID  # 归属用户，仓储层必须按此隔离数据
    workout_id: UUID  # 关联的训练课次
    perceived_exertion: int | None  # sRPE 主观用力程度（1–10），负荷计算核心输入
    subjective_fatigue: int | None  # 主观疲劳自评（1–10）
    soreness: int | None  # 酸痛自评（1–10）
    note: str | None  # 用户自由备注
    created_at: datetime  # 反馈报告时间：判定"是否为未来证据"的时间锚点
    updated_at: datetime

    def __post_init__(self) -> None:
        # frozen dataclass 的构造后钩子：创建实例时立即校验三个量表范围。
        validate_subjective_scale("perceived_exertion", self.perceived_exertion)
        validate_subjective_scale("subjective_fatigue", self.subjective_fatigue)
        validate_subjective_scale("soreness", self.soreness)
