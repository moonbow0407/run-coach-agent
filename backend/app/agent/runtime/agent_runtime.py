"""Agent 推理循环（Runtime）：Context → Reason → Action → Observation → … → Final。

每一轮循环：

    1. Reasoner 基于上下文 + 已发生的调用历史给出一个 Action；
    2. Action 是 FinalAction    → 直接返回，由 ChatService 提交对话；
    3. Action 是 CapabilityCall → 通过可信执行上下文调用领域能力，
       把 Observation 记回 ReasoningState，再进入下一轮 Reason。

Runtime 自己不决定“该调哪个工具”——那是 Reasoner 基于证据的职责；
这里只提供运行保护（步数上限、取消检查）、事件发布和执行轨迹记录。
"""

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
        """执行一次完整的推理循环，直到模型给出最终回答或触发保护/取消。"""
        # 第一步：装配上下文（热上下文 + 历史对话 + 记忆 + 能力清单）。
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

        # 推理循环的工作状态：只存于本次 AgentRun 内存，不落库。
        state = ReasoningState()
        step_index = 0
        while True:
            # 系统保护：防止 Reasoner 无限调用工具；这不是“最多思考几轮”的产品契约。
            if step_index >= self._max_steps:
                raise AgentRuntimeError("超过系统运行保护步数")
            # 让出事件循环，使取消请求有机会被投递；被取消时转为领域取消语义。
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError as exc:
                raise TurnCancelled("AgentRun 已取消") from exc

            await self._lifecycle.publish(
                ReasoningStarted(
                    request_id=command.request_id,
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    step_index=step_index,
                )
            )
            # 请 Reasoner 决定下一步：调用能力，还是给出最终回答。
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
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    step_index=step_index,
                    action_type=action.type,
                )
            )
            step_index += 1

            if isinstance(action, FinalAction):
                # 模型认为证据已足够，给出最终回答 → 交回 ChatService 提交对话。
                await self._trace.record_final(run_id=command.run_id, action=action)
                return action

            if not isinstance(action, CapabilityCallAction):
                # 模型输出了契约之外的东西：fail fast，交由失败语义收尾。
                raise AgentRuntimeError(f"未知 Action 类型: {type(action)!r}")

            # 模型要求调用能力：call_id 用于在轨迹中把调用与观察结果配对。
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
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    capability=action.capability,
                )
            )
            started = perf_counter()
            # 模型参数（arguments）与可信上下文（context）分开传入：
            # user_id 来自命令而非模型输出，保证用户数据隔离。
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
            # 观察结果记回工作状态，下一轮 Reasoner 将看到它并决定是否继续调查。
            state.append(observation)
            await self._trace.record_observation(
                run_id=command.run_id,
                call_id=call_id,
                observation=observation,
            )
            await self._lifecycle.publish(
                CapabilityCompleted(
                    request_id=command.request_id,
                    trace_id=command.trace_id,
                    turn_id=command.turn_id,
                    run_id=command.run_id,
                    call_id=call_id,
                    capability=action.capability,
                    status=observation.status,
                    duration_ms=duration_ms,
                )
            )
