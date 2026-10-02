"""RequestContext：一次请求的可信身份与追踪上下文。

在系统入口（鉴权依赖）构造一次，沿执行链向下传播；
下游所有代码只从这里取 user_id，绝不从请求体 / 模型输出取。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)  # frozen：不可变数据类，防止执行链下游篡改身份与追踪信息
class RequestContext:
    """一次 HTTP 请求的可信身份与追踪上下文。

    user_id 必须来自认证系统，禁止从 Chat Body、LLM 参数或 Tool 参数读取。
    """

    user_id: UUID  # 已认证用户的 ID，下游所有业务只从这里取身份
    request_id: UUID  # 本次请求的唯一 ID，用于日志关联与幂等排查
    trace_id: UUID  # 全链路追踪 ID，跨模块串联一次请求的所有日志
    timestamp: datetime  # 请求进入系统的时刻（UTC）
