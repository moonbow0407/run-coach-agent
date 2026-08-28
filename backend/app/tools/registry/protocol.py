"""Tool 对外协议：定义、参数模型与执行入口。

普通业务 Tool 通过 execute 执行；依赖当前 ToolSession 的发现类系统
Tool（Phase 2 仅 search_tools）通过 execute_for_session 执行，由
Executor 分发。两种形态都不接触 Registry / Search / Resolver 内部状态
（发现类工具经构造注入的只读组件组合会话级流程）。
"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition

if TYPE_CHECKING:
    # 仅供类型标注使用，避免 registry -> protocol -> session 的运行时循环导入。
    from app.tools.resolver.session import ToolSession


@runtime_checkable
class Tool(Protocol):
    """业务 Tool：只用已验证参数与可信上下文执行，不依赖会话状态。

    args 为 args_model 校验后的实例（Executor 保证具体类型与
    args_model 一致），返回值由 Executor 统一 json_ready 归一化。
    """

    @property
    def definition(self) -> ToolDefinition: ...

    @property
    def args_model(self) -> type[BaseModel]: ...

    async def execute(
        self,
        *,
        args: BaseModel,
        context: ToolExecutionContext,
    ) -> object: ...


@runtime_checkable
class SessionAwareTool(Protocol):
    """发现类系统 Tool：执行体需要当前 ToolSession。

    搜索、Registry 再确认、Discovery 更新与结果构造在该执行体内一次
    完成，保证“报告命中的 Tool 集合”与“实际解锁的集合”完全一致。
    """

    @property
    def definition(self) -> ToolDefinition: ...

    @property
    def args_model(self) -> type[BaseModel]: ...

    async def execute_for_session(
        self,
        *,
        args: BaseModel,
        session: "ToolSession",
        context: ToolExecutionContext,
    ) -> object: ...


# Registry 接受的两种 Tool 形态
AnyTool = Tool | SessionAwareTool


class ToolProvider(Protocol):
    """提供一组 Tool；注册生命周期归 Registry，Provider 只负责装配。"""

    def tools(self) -> list[AnyTool]: ...


def parameters_schema_of(args_model: type[BaseModel]) -> dict[str, Any]:
    """由参数模型生成模型可见 JSON Schema。

    模型看到的 Schema 与 Runtime 校验必须同源：这是唯一入口，
    禁止为任何工具手写第二份 Schema。
    """
    return args_model.model_json_schema()
