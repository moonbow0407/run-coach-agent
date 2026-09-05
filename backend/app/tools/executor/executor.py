"""统一 ToolExecutor：存在性 / 可见性 / 参数 / 授权 / 安全闸门 / 超时 / 错误归一化。

每个 Tool 不重复实现治理逻辑；可恢复错误以带 error_code 的
Observation 返回，Runtime 不变量破坏抛 ToolRuntimeError 使
AgentRun failed。取消（CancelledError）与超时是不同控制流：取消
必须向上传播并由 ChatService 持久化 TurnCancelled，绝不转成
tool_timeout 或 tool_execution_failed。
"""

import asyncio
import logging

from pydantic import ValidationError

from app.agent.models.action import ToolCallAction
from app.agent.models.observation import Observation
from app.common.errors import RunCoachError, ToolRuntimeError
from app.infrastructure.jsonutil import json_ready
from app.tools.context import ToolExecutionContext
from app.tools.executor.errors import ToolErrorCode
from app.tools.registry.definition import ToolRisk
from app.tools.registry.protocol import SessionAwareTool
from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.resolver import ToolResolver
from app.tools.resolver.session import ToolSession
from app.tools.safety.gate import SafetyGate

logger = logging.getLogger(__name__)

# 模型可直接执行的风险等级白名单；MUTATING 只能走用户确认流程。
_MODEL_EXECUTABLE_RISKS = frozenset({ToolRisk.READ_ONLY, ToolRisk.ANALYZE, ToolRisk.DRAFT})


class ToolExecutor:
    """统一执行器：治理顺序与错误归一化集中在此，工具只需实现业务。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        resolver: ToolResolver,
        safety_gate: SafetyGate | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._safety_gate = safety_gate  # 可选：DRAFT/MUTATING 执行前的教练安全闸门

    async def execute(
        self,
        *,
        action: ToolCallAction,
        session: ToolSession,
        context: ToolExecutionContext,
    ) -> Observation:
        """按固定治理顺序执行一次 ToolCallAction。"""
        name = action.tool

        # 1. 存在性：Registry 是唯一事实来源。
        entry = self._registry.find(name)
        if entry is None:
            return _error_observation(action, ToolErrorCode.TOOL_NOT_FOUND, f"工具不存在: {name}")

        # 2. Session 可用性：会话必须属于当前 AgentRun。
        #    不一致属于 Runtime 不变量破坏，使 AgentRun failed，不能伪装成 Tool 错误。
        if session.run_id != context.run_id:
            raise ToolRuntimeError(
                f"ToolSession 与当前 AgentRun 不一致: {session.run_id} != {context.run_id}"
            )

        # 3. 可见性：隐藏 Tool 猜测绝不执行（Registry 中存在也不行）。
        if not self._resolver.is_visible(session, name):
            return _error_observation(
                action,
                ToolErrorCode.TOOL_NOT_AVAILABLE,
                f"工具当前不可见: {name}；可用 search_tools 查找可用工具",
            )

        # 4. 参数验证：与模型可见 Schema 同源的参数模型，拒绝未知字段
        #    （含模型注入的 user_id 等身份信息）。
        try:
            args = entry.args_model.model_validate(action.arguments)
        except ValidationError as exc:
            return _error_observation(
                action, ToolErrorCode.INVALID_ARGUMENTS, _validation_message(exc)
            )

        # 5. 授权：模型可执行 READ_ONLY / ANALYZE / DRAFT；MUTATING 一律拒绝。
        if entry.definition.risk not in _MODEL_EXECUTABLE_RISKS:
            return _error_observation(
                action,
                ToolErrorCode.TOOL_NOT_AUTHORIZED,
                f"工具未获执行授权（不允许 {entry.definition.risk.value}）: {name}",
            )

        # 5b. 教练安全闸门：DRAFT/MUTATING 在执行前硬拦截不安全提案。
        if self._safety_gate is not None and self._safety_gate.requires_check(
            entry.definition.risk
        ):
            decision = await self._safety_gate.check(
                user_id=context.user_id, definition=entry.definition
            )
            if not decision.allowed:
                reason = decision.reason_code or "safety_blocked"
                detail = decision.message or f"安全策略拦截: {name}"
                return _error_observation(
                    action,
                    ToolErrorCode.SAFETY_BLOCKED,
                    f"[{reason}] {detail}",
                )

        # 6/7. timeout 统一控制 + 执行 + 结果归一化。
        try:
            if isinstance(entry.tool, SessionAwareTool):
                coroutine = entry.tool.execute_for_session(
                    args=args, session=session, context=context
                )
            else:
                coroutine = entry.tool.execute(args=args, context=context)
            result = await asyncio.wait_for(coroutine, timeout=entry.definition.timeout_s)
            data = json_ready(result)
        except TimeoutError:
            # 仅 wait_for 的超时走这里；CancelledError 是 BaseException，不会被捕获。
            return _error_observation(action, ToolErrorCode.TOOL_TIMEOUT, f"工具执行超时: {name}")
        except ToolRuntimeError:
            # Runtime 不变量错误必须使 AgentRun 失败，不能降级为可恢复 Observation。
            raise
        except RunCoachError as exc:
            # 预期应用异常：消息已归一化，可安全返回给 Reasoner 继续推理。
            return _error_observation(action, ToolErrorCode.TOOL_EXECUTION_FAILED, str(exc))
        except Exception:
            # 未知异常：只记录内部结构化日志，向 Reasoner 返回通用失败，
            # 不泄漏堆栈或基础设施细节。
            logger.exception(
                "tool.execution.unexpected_error",
                extra={
                    "request_id": str(context.request_id),
                    "trace_id": str(context.trace_id),
                    "user_id": str(context.user_id),
                    "run_id": str(context.run_id),
                    "tool": name,
                    "call_id": str(context.call_id),
                },
            )
            return _error_observation(
                action, ToolErrorCode.TOOL_EXECUTION_FAILED, f"工具执行失败: {name}"
            )

        return Observation(
            source=name,
            status="success",
            data=data,
            model_call_id=action.model_call_id,
        )


def _error_observation(
    action: ToolCallAction, error_code: ToolErrorCode, message: str
) -> Observation:
    """构造带错误码的错误 Observation，交回 Reasoner 继续推理。"""
    return Observation(
        source=action.tool,
        status="error",
        error_code=error_code.value,
        error=message,
        model_call_id=action.model_call_id,
    )


def _validation_message(exc: ValidationError) -> str:
    """把参数校验错误转成面向模型的安全说明（只含字段位置与原因）。"""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "参数校验失败: " + "; ".join(parts)
