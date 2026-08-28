import asyncio
from time import perf_counter
from uuid import uuid4

from app.agent.context.assembler import ContextAssembler
from app.agent.context.bundle import ContextAssemblyRequest
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.lifecycle.events import (
    CapabilityCompleted,
    CapabilityStarted,
    ContextAssembled,
    ContextAssemblyStarted,
    ReasoningCompleted,
    ReasoningStarted,
)
from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.ports.capability_executor import CapabilityExecutionContext, CapabilityExecutor
from app.agent.ports.trace_recorder import AgentTraceRecorder
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.reasoner import Reasoner
from app.agent.reasoning.state import ReasoningState
from app.agent.runtime.run_context import AgentTurnCommand
from app.common.errors import AgentRuntimeError, TurnCancelled


class AgentRuntime:
    """只负责 Context → Reason → Action → Observation → Reason → Final。

    不创建 Turn / AgentRun，不提交 Conversation，不读取 RunStep 驱动决策。
    """

    def __init__(
        self,
        reasoner: Reasoner,
        context_assembler: ContextAssembler,
        capability_executor: CapabilityExecutor,
        lifecycle: LifecycleDispatcher,
        trace_recorder: AgentTraceRecorder,
        max_steps: int,
    ) -> None:
        self._reasoner = reasoner
        self._assembler = context_assembler
        self._executor = capability_executor
        self._lifecycle = lifecycle
        self._trace = trace_recorder
        self._max_steps = max_steps

    async def run(self, command: AgentTurnCommand) -> FinalAction:
        await self._lifecycle.publish(
            ContextAssemblyStarted(
                request_id=command.request_id,
                turn_id=command.turn_id,
                run_id=command.run_id,
            )
        )
        bundle = await self._assembler.assemble(
            ContextAssemblyRequest(
                user_id=command.user_id,
                thread_id=command.thread_id,
                turn_id=command.turn_id,
                current_input=command.current_input,
            )
        )
        await self._lifecycle.publish(
            ContextAssembled(
                request_id=command.request_id,
                turn_id=command.turn_id,
                run_id=command.run_id,
            )
        )

        state = ReasoningState()
        step_index = 0
        while True:
            if step_index >= self._max_steps:
                raise AgentRuntimeError("超过系统运行保护步数")
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError as exc:
                raise TurnCancelled("AgentRun 已取消") from exc

            await self._lifecycle.publish(
                ReasoningStarted(
                    request_id=command.request_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    step_index=step_index,
                )
            )
            action = await self._reasoner.reason(
                ReasoningContext(context_bundle=bundle, state=state)
            )
            await self._trace.record_reasoning(
                run_id=command.run_id,
                action_type=action.type,
            )
            await self._lifecycle.publish(
                ReasoningCompleted(
                    request_id=command.request_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    step_index=step_index,
                    action_type=action.type,
                )
            )
            step_index += 1

            if isinstance(action, FinalAction):
                await self._trace.record_final(run_id=command.run_id, action=action)
                return action

            if not isinstance(action, CapabilityCallAction):
                raise AgentRuntimeError(f"未知 Action 类型: {type(action)!r}")

            call_id = uuid4()
            await self._trace.record_action(
                run_id=command.run_id,
                call_id=call_id,
                action=action,
            )
            state.append(action)

            await self._lifecycle.publish(
                CapabilityStarted(
                    request_id=command.request_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    capability=action.capability,
                )
            )
            started = perf_counter()
            observation = await self._executor.execute(
                name=action.capability,
                arguments=action.arguments,
                context=CapabilityExecutionContext(
                    user_id=command.user_id,
                    run_id=command.run_id,
                    turn_id=command.turn_id,
                    request_id=command.request_id,
                    timestamp=command.timestamp,
                ),
            )
            duration_ms = int((perf_counter() - started) * 1000)
            state.append(observation)
            await self._trace.record_observation(
                run_id=command.run_id,
                call_id=call_id,
                observation=observation,
            )
            await self._lifecycle.publish(
                CapabilityCompleted(
                    request_id=command.request_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    capability=action.capability,
                    status=observation.status,
                    duration_ms=duration_ms,
                )
            )
