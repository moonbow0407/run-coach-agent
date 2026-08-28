"""单元测试共享的 Tool 替身。"""

from pydantic import BaseModel, ConfigDict

from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource


class SampleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class SampleTool:
    """可配置名称与 always-on 的最小 Tool 替身。"""

    def __init__(self, name: str, *, always_on: bool = False, timeout_s: float = 5.0) -> None:
        self._name = name
        self._always_on = always_on
        self._timeout_s = timeout_s

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=f"{self._name} tool for unit tests",
            tags=(self._name,),
            search_hint=f"hint for {self._name}",
            always_on=self._always_on,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.SYSTEM,
            timeout_s=self._timeout_s,
        )

    @property
    def args_model(self) -> type[SampleArgs]:
        return SampleArgs

    async def execute(self, *, args: SampleArgs, context: ToolExecutionContext) -> object:
        return {"name": self._name, "value": args.value}
