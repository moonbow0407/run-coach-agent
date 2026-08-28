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
from app.identity.application.request_context import RequestContext


@dataclass(frozen=True)
class ChatResult:
    thread_id: UUID
    turn_id: UUID
    message_id: UUID
    content: str
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
        self._store = conversation_store
        self._runtime = runtime
        self._lifecycle = lifecycle

    async def send_message(
        self,
        *,
        request_context: RequestContext,
        thread_id: UUID | None,
        content: str,
    ) -> ChatResult:
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
            committed = await self._commit(
                request_context=request_context,
                started=started,
                final=final,
            )
        except (asyncio.CancelledError, TurnCancelledError):
            await self._store.cancel_turn(
                user_id=request_context.user_id,
                turn_id=started.turn.id,
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
            await self._store.fail_turn(
                user_id=request_context.user_id,
                turn_id=started.turn.id,
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
            if isinstance(exc, RunCoachError):
                raise
            raise RunCoachError("Agent 执行失败") from exc

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
        )
        return committed
