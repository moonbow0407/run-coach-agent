"""ChatService：一次用户交互的应用层编排器。

一轮对话的完整流程（对应 ARCHITECTURE §44 的两个短事务）：

    事务 A（start_turn）  创建 Thread（如首次）+ Turn + 用户消息 + AgentRun，提交
      → 发布 TurnStarted
    AgentRuntime.run       推理循环，期间不持有数据库事务
      → 事务 B（commit_turn）写入助手消息，Turn / AgentRun 置为 committed
      → 发布 TurnCommitted
    失败 → fail_turn + TurnFailed；取消 → cancel_turn + TurnCancelled

ChatService 拥有 Thread / Message / Turn / AgentRun 的生命周期；
AgentRuntime 只负责推理循环，二者职责严格分离。
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.lifecycle.events import (
    TurnCancelled,
    TurnCommitStarted,
    TurnCommitted,
    TurnFailed,
    TurnStarted,
)
from app.agent.models.action import FinalAction
from app.agent.ports.conversation_store import CommittedTurn, ConversationStore, StartedTurn
from app.agent.runtime.agent_runtime import AgentRuntime
from app.agent.runtime.run_context import AgentTurnCommand
from app.common.errors import RunCoachError
from app.common.errors import TurnCancelled as TurnCancelledError
from app.common.events import EventMetadata
from app.identity.application.request_context import RequestContext


@dataclass(frozen=True)
class ChatResult:
    """一轮对话的结果快照：最终回答 + 前端后续引用所需的全部 ID。"""

    thread_id: UUID
    turn_id: UUID
    message_id: UUID  # 本轮助手消息 ID
    content: str  # 助手最终回答文本
    run_id: UUID


class ChatService:
    """一次用户交互的 Application Orchestrator。

    拥有 Thread / Message / Turn / AgentRun 的生命周期与事务边界。
    AgentRuntime 只负责 reasoning loop。
    """

    def __init__(
        self,
        conversation_store: ConversationStore,
        runtime: AgentRuntime,
        lifecycle: LifecycleDispatcher,
    ) -> None:
        self._store = conversation_store  # 会话存储端口：Thread/Turn 消息的事务边界
        self._runtime = runtime  # Agent 推理循环，只负责 reasoning
        self._lifecycle = lifecycle  # 生命周期事件分发

    async def send_message(
        self,
        *,
        request_context: RequestContext,
        thread_id: UUID | None,
        content: str,
    ) -> ChatResult:
        """处理一条用户消息并返回助手回答。

        全程不使用一个跨越 LLM 调用的长事务：开始与提交是两个独立短事务。
        """
        # 事务 A：创建 / 找到 Thread，写入 Turn、用户消息、AgentRun，状态置为 running。
        started = await self._store.start_turn(
            user_id=request_context.user_id,
            thread_id=thread_id,
            content=content,
        )

        try:
            await self._lifecycle.publish(
                TurnStarted(
                    request_id=request_context.request_id,
                    trace_id=request_context.trace_id,
                    turn_id=started.turn.id,
                    thread_id=started.thread.id,
                    user_id=request_context.user_id,
                    run_id=started.run.id,
                    started_at=started.turn.started_at,
                )
            )
            # 推理循环：期间可能发生多次能力调用，全部由 Runtime 内部管理。
            final = await self._runtime.run(
                AgentTurnCommand(
                    user_id=request_context.user_id,
                    thread_id=started.thread.id,
                    turn_id=started.turn.id,
                    run_id=started.run.id,
                    request_id=request_context.request_id,
                    trace_id=request_context.trace_id,
                    timestamp=request_context.timestamp,
                    current_input=content,
                )
            )
            # 事务 B：写入助手消息，Turn / AgentRun 置为 committed。
            committed = await self._commit(
                request_context=request_context,
                started=started,
                final=final,
            )
        except (asyncio.CancelledError, TurnCancelledError):
            # 取消与失败语义不同：取消不是错误。Turn 置为 cancelled，
            # 已写入的用户消息保留，但不产生助手消息，也不进入长期记忆。
            await self._store.cancel_turn(
                user_id=request_context.user_id,
                turn_id=started.turn.id,
                event_metadata=_event_metadata(request_context),
            )
            await self._lifecycle.publish_after_commit(
                TurnCancelled(
                    request_id=request_context.request_id,
                    trace_id=request_context.trace_id,
                    turn_id=started.turn.id,
                    thread_id=started.thread.id,
                    user_id=request_context.user_id,
                    run_id=started.run.id,
                )
            )
            raise
        except Exception as exc:
            # 统一失败语义：Turn / AgentRun 置为 failed，发布 TurnFailed。
            await self._store.fail_turn(
                user_id=request_context.user_id,
                turn_id=started.turn.id,
                event_metadata=_event_metadata(request_context),
            )
            await self._lifecycle.publish_after_commit(
                TurnFailed(
                    request_id=request_context.request_id,
                    trace_id=request_context.trace_id,
                    turn_id=started.turn.id,
                    thread_id=started.thread.id,
                    user_id=request_context.user_id,
                    run_id=started.run.id,
                    error=str(exc),
                )
            )
            # 应用内已知错误原样上抛；其它异常（含基础设施细节）归一化为
            # RunCoachError，避免向 API 层泄漏数据库连接串、堆栈等敏感信息。
            if isinstance(exc, RunCoachError):
                raise
            raise RunCoachError("Agent 执行失败") from exc

        # publish_after_commit：终态事件在状态已落库之后发布，监听方失败不影响业务结果。
        await self._lifecycle.publish_after_commit(
            TurnCommitted(
                request_id=request_context.request_id,
                trace_id=request_context.trace_id,
                turn_id=committed.turn.id,
                thread_id=committed.thread.id,
                user_id=request_context.user_id,
                user_message_id=committed.turn.user_message_id,
                assistant_message_id=committed.assistant_message.id,
                run_id=committed.run.id,
                committed_at=committed.turn.committed_at or request_context.timestamp,
            )
        )
        return ChatResult(
            thread_id=committed.thread.id,
            turn_id=committed.turn.id,
            message_id=committed.assistant_message.id,
            content=committed.assistant_message.content,
            run_id=committed.run.id,
        )

    async def _commit(
        self,
        *,
        request_context: RequestContext,
        started: StartedTurn,
        final: FinalAction,
    ) -> CommittedTurn:
        """提交一轮成功对话：发布 TurnCommitStarted，然后写入助手消息并落终态。"""
        await self._lifecycle.publish(
            TurnCommitStarted(
                request_id=request_context.request_id,
                trace_id=request_context.trace_id,
                turn_id=started.turn.id,
                thread_id=started.thread.id,
                run_id=started.run.id,
            )
        )
        committed = await self._store.commit_turn(
            user_id=request_context.user_id,
            turn_id=started.turn.id,
            assistant_content=final.content,
            event_metadata=_event_metadata(request_context),
        )
        return committed


def _event_metadata(context: RequestContext) -> EventMetadata:
    """只从可信请求上下文构造 durable event 追踪元数据。"""
    return EventMetadata(
        correlation_id=context.request_id,
        trace_id=context.trace_id,
    )
