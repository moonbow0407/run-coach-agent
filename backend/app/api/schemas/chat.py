"""聊天接口的请求 / 响应模型（DTO）。

API 层用 Pydantic 模型做校验与序列化，进入业务层后一律转为领域对象。
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """发起一轮对话。thread_id 为空表示新建对话线程。

    extra="forbid"：拒绝未知字段，避免客户端拼错的字段被静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    thread_id: UUID | None = None  # 现有线程 ID；为空表示新建线程
    message: str = Field(min_length=1)  # 用户本轮消息内容，不允许空串


class SessionDiffSummary(BaseModel):
    """待确认计划调整中的单节课摘要（对话 CTA 用）。"""

    model_config = ConfigDict(extra="forbid")

    scheduled_date: date  # 课次日期
    from_type: str  # 原课型
    to_type: str  # 新课型
    old_title: str  # 原标题
    new_title: str  # 新标题


class PendingPlanChangeSummary(BaseModel):
    """未解决计划调整的精简摘要：对话结束后挂在 ChatResponse 上供 CTA。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    change_type: str  # 调整类型
    reason: str  # 面向用户的调整理由
    status: str  # draft / pending_confirmation 等
    from_plan_version: int  # 基于的计划版本
    session_diffs: list[SessionDiffSummary]  # 课次变更摘要


class ChatResponse(BaseModel):
    """同步聊天接口的响应：最终回答 + 本轮各对象的 ID（供前端后续引用）。"""

    thread_id: UUID
    turn_id: UUID  # 本轮对话（Turn）的 ID
    message_id: UUID
    content: str  # 助手最终回答文本
    pending_plan_change: PendingPlanChangeSummary | None = None  # 未解决提案摘要
    actions: list[str] = Field(default_factory=list)  # 可用 CTA 动作名


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


class ChatResumeRequest(BaseModel):
    """从失败 Run 的最新检查点续跑。"""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID  # 失败的 AgentRun id
