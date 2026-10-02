"""对话线程：用户与教练长期会话的容器，所有 Message 都挂在线程下。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


# frozen=True：不可变数据类，实例创建后字段不可修改，防止领域对象被误改
@dataclass(frozen=True)
class Thread:
    """一个对话线程。thread 无业务状态，只承载消息的时间线。"""

    id: UUID
    user_id: UUID  # 归属用户：每个线程只属于一个跑者
    created_at: datetime  # 线程创建时间
    updated_at: datetime  # 最近一次消息活动时间，用于会话列表排序
