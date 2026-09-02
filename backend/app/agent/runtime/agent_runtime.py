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
    ResponseDelta,
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
        self._reasoner = reasoner  # 推理器：决定下一步回复还是调工具
        self._assembler = context_assembler  # 上下文装配器
        self._tool_runtime = tool_runtime  # 工具运行时：负责 Tool 解析与执行
        self._lifecycle = lifecycle  # 生命周期事件分发
        self._trace = trace_recorder  # 执行轨迹记录端口
        self._max_steps = max_steps  # 单次 Run 的推理步数上限（运行保护）

    async def run(self, command: AgentTurnCommand) -> FinalAction:
        """执行一次完整推理循环，返回最终回答，交由上层提交对话。"""
        await self._lifecycle.publish(
            ContextAssemblyStarted(
                request_id=command.request_id,
                trace_id=command.trace_id,
                turn_id=command.turn_id,
                run_id=command.run_id,
            )
        )
        # 装配本轮完整上下文：热上下文 + 已提交历史 + 长期记忆
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
        state = ReasoningState()  # Run 内工作状态：工具调用与结果的交互序列
        step_index = 0
        while True:
            # 运行保护：步数超限说明模型可能在无限循环调工具，强制失败
            if step_index >= self._max_steps:
                raise AgentRuntimeError("超过系统运行保护步数")
            try:
                # 主动让出控制权，使取消信号能在此检查点生效
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
            # 文本增量回调：流式产出最终回答时逐片段经生命周期总线转发给
            # SSE 等监听方；仅进程内事件，不持久化。闭包按步新建，并用默认
            # 参数绑定当前步序，避免读到循环后续步的 step_index。
            async def on_text_delta(delta: str, step: int = step_index) -> None:
                await self._lifecycle.publish(
                    ResponseDelta(
                        request_id=command.request_id,
                        trace_id=command.trace_id,
                        turn_id=command.turn_id,
                        run_id=command.run_id,
                        step_index=step,
                        delta=delta,
                    )
                )

            action = await self._reasoner.reason(
                ReasoningContext(
                    context_bundle=bundle,
                    state=state,
                    visible_tools=visible_tools,
                ),
                on_text_delta=on_text_delta,
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
                # 推理结束：最终回答交回 ChatService 提交对话
                await self._trace.record_final(run_id=command.run_id, action=action)
                return action

            if not isinstance(action, ToolCallAction):
                # 防御分支：未来新增 Action 类型未接入循环时尽早失败
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
