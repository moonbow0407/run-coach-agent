"""RequestContext：一次请求的可信身份与追踪上下文。

在系统入口（鉴权依赖）构造一次，沿执行链向下传播；
下游所有代码只从这里取 user_id，绝不从请求体 / 模型输出取。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class RequestContext:
    """一次 HTTP 请求的可信身份与追踪上下文。

    user_id 必须来自认证系统，禁止从 Chat Body、LLM 参数或 Capability 参数读取。
    """

    user_id: UUID
    request_id: UUID
    trace_id: UUID
    timestamp: datetime
