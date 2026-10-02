"""用户领域模型。Phase 1 用户无个人属性字段，身份由认证承载。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)  # frozen：不可变数据类，用户对象创建后不允许就地修改
class User:
    """用户领域模型：仅承载身份标识与审计时间，具体业务属性由各阶段按需扩展。"""

    id: UUID
    created_at: datetime  # 用户创建时刻（UTC）
    updated_at: datetime  # 记录最后一次更新时刻（UTC）
