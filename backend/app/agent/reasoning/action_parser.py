"""模型输出 → 结构化 Action 的解析与校验。

模型输出不可信：JSON 不合法或不符合输出契约，一律归一化为
ReasonerError，由上层按推理失败处理，而不是猜测修复。
"""

import json
import re

from pydantic import TypeAdapter, ValidationError

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.common.errors import ReasonerError

_ACTION_ADAPTER: TypeAdapter[CapabilityCallAction | FinalAction] = TypeAdapter(
    CapabilityCallAction | FinalAction
)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_agent_action(raw: str) -> CapabilityCallAction | FinalAction:
    """把模型原始输出解析为两种合法 Action 之一，其余情况抛 ReasonerError。"""
    text = raw.strip()
    # 容忍模型把 JSON 包在 ``` 代码块里输出：先剥掉围栏再解析。
    if text.startswith("```"):
        text = _FENCE.sub("", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReasonerError("Reasoner 输出不是合法 JSON") from exc
    try:
        return _ACTION_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ReasonerError("Reasoner 输出不是合法 Action") from exc
