"""跨模块共享的类型别名：让签名表达业务语义而不是裸 UUID。"""

from datetime import datetime
from typing import TypeAlias
from uuid import UUID

UserId: TypeAlias = UUID
ThreadId: TypeAlias = UUID
TurnId: TypeAlias = UUID
RunId: TypeAlias = UUID
UTCDateTime: TypeAlias = datetime
