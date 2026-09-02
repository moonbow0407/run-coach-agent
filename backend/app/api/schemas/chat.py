"""聊天接口的请求 / 响应模型（DTO）。

API 层用 Pydantic 模型做校验与序列化，进入业务层后一律转为领域对象。
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """发起一轮对话。thread_id 为空表示新建对话线程。

    extra="forbid"：拒绝未知字段，避免客户端拼错的字段被静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    thread_id: UUID | None = None  # 现有线程 ID；为空表示新建线程
    message: str = Field(min_length=1)  # 用户本轮消息内容，不允许空串


class ChatResponse(BaseModel):
    """同步聊天接口的响应：最终回答 + 本轮各对象的 ID（供前端后续引用）。"""

    thread_id: UUID
    turn_id: UUID  # 本轮对话（Turn）的 ID
    message_id: UUID
    content: str  # 助手最终回答文本


class MessageResponse(BaseModel):
    """历史消息条目。"""

    id: UUID
    role: str  # 消息角色（user / assistant）
    content: str  # 消息内容
    created_at: str  # 创建时间（ISO 格式字符串）


class ThreadMessagesResponse(BaseModel):
    """某个对话线程的完整历史消息列表。"""

    thread_id: UUID
    messages: list[MessageResponse]  # 历史消息列表
