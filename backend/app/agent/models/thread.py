"""对话线程：用户与教练长期会话的容器，所有 Message 都挂在线程下。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Thread:
    """一个对话线程。thread 无业务状态，只承载消息的时间线。"""

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
