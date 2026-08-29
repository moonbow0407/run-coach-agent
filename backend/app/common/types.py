"""跨模块共享的类型别名：让签名表达业务语义而不是裸 UUID。"""

from datetime import datetime
from uuid import UUID

type UserId = UUID
type ThreadId = UUID
type TurnId = UUID
type RunId = UUID
type UTCDateTime = datetime
