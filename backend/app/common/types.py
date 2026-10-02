"""跨模块共享的类型别名：让签名表达业务语义而不是裸 UUID。"""

from datetime import datetime
from uuid import UUID

# type 别名（PEP 695 语法）：只给 UUID / datetime 起业务名字，运行时与原类型等价。
type UserId = UUID  # 用户唯一标识
type ThreadId = UUID  # Thread：会话线程
type TurnId = UUID  # Turn：一轮对话（用户消息 + 助手回复）
type RunId = UUID  # Run：一次 Agent 推理运行
type UTCDateTime = datetime  # 约定存放 UTC 时刻（靠口径约束，类型系统不强制）
