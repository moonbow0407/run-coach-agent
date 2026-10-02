"""ReasoningState：当前 AgentRun 的内存工作状态。

只保存 ToolCallAction 与 Observation，不落库、不保存隐藏思维链、
不从 RunStep 恢复驱动正常执行。native tool calling 要求交互序列
严格为 ToolCallAction → 同 model_call_id 的 Observation；违反属于
Runtime 不变量错误，立即失败。
"""

from dataclasses import dataclass, field

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.observation import Observation
from app.common.errors import AgentRuntimeError

# Run 内一次交互 = 一次工具调用请求，或该请求对应的结果
ReasoningInteraction = ToolCallAction | Observation


@dataclass
class ReasoningState:
    """当前 AgentRun 内存中的工作状态。不保存隐藏思维链，不落库。"""

    interactions: list[ReasoningInteraction] = field(default_factory=list)  # 严格交替的 ToolCall → Observation 序列

    def __init__(self, interactions: list[ReasoningInteraction] | None = None) -> None:
        # 显式 __init__ 以校验构造时传入的序列（测试快照也会走这里）。
        self.interactions = []
        self._seen_model_call_ids: set[str] = set()  # 已出现的协议 ID，用于查重
        for item in interactions or []:
            self.append(item)

    def append(self, item: ReasoningInteraction) -> None:
        # FinalAction 是推理终点，交由 Runtime 返回，不属于工作状态
        if isinstance(item, FinalAction):
            raise AgentRuntimeError("FinalAction 不得进入 ReasoningState")
        if isinstance(item, ToolCallAction):
            self._append_tool_call(item)
            return
        self._append_observation(item)

    def _append_tool_call(self, action: ToolCallAction) -> None:
        last = self.interactions[-1] if self.interactions else None
        # 连续两次工具调用：上一次还没拿到结果，违反 native 协议交替约束
        if isinstance(last, ToolCallAction):
            raise AgentRuntimeError("上一个 ToolCallAction 尚无对应的 Observation")
        # 同一个协议 ID 不允许调用两次：防止结果配对错乱
        if action.model_call_id in self._seen_model_call_ids:
            raise AgentRuntimeError(f"model_call_id 重复: {action.model_call_id}")
        self._seen_model_call_ids.add(action.model_call_id)
        self.interactions.append(action)

    def _append_observation(self, observation: Observation) -> None:
        last = self.interactions[-1] if self.interactions else None
        # 结果必须紧跟在工具调用之后，否则序列不完整
        if not isinstance(last, ToolCallAction):
            raise AgentRuntimeError("Observation 之前必须紧邻 ToolCallAction")
        if observation.model_call_id != last.model_call_id:
            raise AgentRuntimeError(
                f"Observation 的 model_call_id 与 ToolCallAction 不一致: "
                f"{observation.model_call_id} != {last.model_call_id}"
            )
        self.interactions.append(observation)
