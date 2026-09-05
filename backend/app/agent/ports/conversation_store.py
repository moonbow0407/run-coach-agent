"""会话写端口：Conversation 生命周期（开始 / 提交 / 失败 / 取消）的事务边界。

每个方法对应一次独立短事务，保证事务不跨越 LLM 调用（ARCHITECTURE §44）。
实现方负责校验用户归属（user_id 匹配）与状态合法性。
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.agent.models.message import Message
from app.agent.models.run import AgentRun
from app.agent.models.thread import Thread
from app.agent.models.turn import Turn
from app.common.events import EventMetadata


@dataclass(frozen=True)
class StartedTurn:
    """start_turn 的产物：新 Turn、用户消息与 AgentRun 均已落库。"""

    thread: Thread  # 新建或已有的会话线程
    turn: Turn  # 状态为 running 的新 Turn
    user_message: Message  # 本轮用户消息
    run: AgentRun  # 与 Turn 配套创建的 AgentRun


@dataclass(frozen=True)
class CommittedTurn:
    """commit_turn 的产物：助手消息已落库，Turn 置为 committed。"""

    thread: Thread  # 会话线程
    turn: Turn  # 已置为 committed 的 Turn
    assistant_message: Message  # 本轮助手回复
    run: AgentRun  # 已置为 completed 的 AgentRun


# Protocol（结构化鸭子类型）：只约束方法签名，实现方无需显式继承本类
class ConversationStore(Protocol):
    """Conversation 生命周期的事务边界。每个方法都是一次短事务。"""

    # 创建（或复用）线程，写入 Turn、用户消息与 AgentRun，状态置 running
    async def start_turn(
        self,
        *,
        user_id: UUID,
        thread_id: UUID | None,
        content: str,
    ) -> StartedTurn: ...

    # 写入助手消息，Turn / AgentRun 置为 committed
    async def commit_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        assistant_content: str,
        event_metadata: EventMetadata,
    ) -> CommittedTurn: ...

    # Turn / AgentRun 置为 failed；已写入的用户消息保留
    async def fail_turn(
        self, *, user_id: UUID, turn_id: UUID, event_metadata: EventMetadata
    ) -> None: ...

    # Turn / AgentRun 置为 cancelled；用户消息保留，不产生助手消息
    async def cancel_turn(
        self, *, user_id: UUID, turn_id: UUID, event_metadata: EventMetadata
    ) -> None: ...

    # 将 FAILED 的 Turn / AgentRun 重新置为 running，供检查点续跑
    async def reopen_failed_turn(self, *, user_id: UUID, turn_id: UUID) -> StartedTurn: ...
