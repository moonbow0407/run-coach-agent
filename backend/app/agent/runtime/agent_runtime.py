"""Agent 推理循环（Runtime）：Context → Reason → Action → Observation → … → Final。

每一轮循环：

    1. Reasoner 基于上下文 + 当前可见 Tool + 已发生的调用历史给出一个 Action；
    2. Action 是 FinalAction  → 直接返回，由 ChatService 提交对话；
    3. Action 是 ToolCallAction → 通过可信执行上下文执行工具，
       把 Observation 记回 ReasoningState，再进入下一轮 Reason。

Runtime 自己不决定“该调哪个工具”——那是 Reasoner 基于证据的职责；
这里只提供运行保护（步数上限、取消检查）、事件发布和执行轨迹记录。
Tool 细节全部委托 ToolRuntime，本类不接触 Registry / Search / Resolver
或工具参数模型。
"""

import asyncio
from time import perf_counter
from uuid import uuid4

from app.agent.context.assembler import ContextAssembler
from app.agent.context.bundle import ContextAssemblyRequest
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.lifecycle.events import (
    ContextAssembled,
    ContextAssemblyStarted,
    ReasoningCompleted,
    ReasoningStarted,
    ToolCompleted,
    ToolStarted,
)
from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.ports.trace_recorder import AgentTraceRecorder
from app.agent.reasoning.models import ReasoningContext
from app.agent.reasoning.reasoner import Reasoner
from app.agent.reasoning.state import ReasoningState
from app.agent.runtime.run_context import AgentTurnCommand
from app.common.errors import AgentRuntimeError, TurnCancelled
from app.tools.context import ToolExecutionContext
from app.tools.runtime import ToolRuntime


class AgentRuntime:
    """只负责 Context → Reason → Action → Observation → Reason → Final。

    不创建 Turn / AgentRun，不提交 Conversation，不读取 RunStep 驱动决策。
    """

    def __init__(
        self,
        reasoner: Reasoner,
        context_assembler: ContextAssembler,
        tool_runtime: ToolRuntime,
        lifecycle: LifecycleDispatcher,
        trace_recorder: AgentTraceRecorder,
        max_steps: int,
    ) -> None:
        self._reasoner = reasoner
        self._assembler = context_assembler
        self._tool_runtime = tool_runtime
        self._lifecycle = lifecycle
        self._trace = trace_recorder
        self._max_steps = max_steps

    async def run(self, command: AgentTurnCommand) -> FinalAction:
        await self._lifecycle.publish(
            ContextAssemblyStarted(
                request_id=command.request_id,
                trace_id=command.trace_id,
                turn_id=command.turn_id,
                run_id=command.run_id,
            )
        )
        bundle = await self._assembler.assemble(
            ContextAssemblyRequest(
                user_id=command.user_id,
                thread_id=command.thread_id,
                turn_id=command.turn_id,
                timestamp=command.timestamp,
                current_input=command.current_input,
            )
        )
        await self._lifecycle.publish(
            ContextAssembled(
                request_id=command.request_id,
                trace_id=command.trace_id,
                turn_id=command.turn_id,
                run_id=command.run_id,
            )
        )

        # 每个 AgentRun 一个 ToolSession：Run-local Discovery 不跨 Turn 复用，
        # Run 结束后随局部变量直接销毁。
        session = self._tool_runtime.create_session(run_id=command.run_id)
        state = ReasoningState()
        step_index = 0
        while True:
            if step_index >= self._max_steps:
                raise AgentRuntimeError("超过系统运行保护步数")
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError as exc:
                raise TurnCancelled("AgentRun 已取消") from exc

            # 每轮重新解析当前可见 Tool：search_tools 的发现即时生效。
            visible_tools = self._tool_runtime.visible_tools(session)

            await self._lifecycle.publish(
                ReasoningStarted(
                    request_id=command.request_id,
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    step_index=step_index,
                )
            )
            action = await self._reasoner.reason(
                ReasoningContext(
                    context_bundle=bundle,
                    state=state,
                    visible_tools=visible_tools,
                )
            )
            await self._trace.record_reasoning(
                run_id=command.run_id,
                action_type=action.type,
            )
            await self._lifecycle.publish(
                ReasoningCompleted(
                    request_id=command.request_id,
                    trace_id=command.trace_id,
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

            if not isinstance(action, ToolCallAction):
                raise AgentRuntimeError(f"未知 Action 类型: {type(action)!r}")

            # 内部 UUID call_id 服务 ToolExecutionContext / Lifecycle / RunStep；
            # 模型协议 ID（model_call_id）由 Action 与 Observation 自带，两者不混用。
            call_id = uuid4()
            await self._trace.record_action(
                run_id=command.run_id,
                call_id=call_id,
                action=action,
            )
            state.append(action)

            await self._lifecycle.publish(
                ToolStarted(
                    request_id=command.request_id,
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    tool=action.tool,
                )
            )
            started = perf_counter()
            observation = await self._tool_runtime.execute_tool_call(
                session=session,
                action=action,
                context=ToolExecutionContext(
                    user_id=command.user_id,
                    thread_id=command.thread_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    request_id=command.request_id,
                    trace_id=command.trace_id,
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
                ToolCompleted(
                    request_id=command.request_id,
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    tool=action.tool,
                    status=observation.status,
                    duration_ms=duration_ms,
                )
            )
