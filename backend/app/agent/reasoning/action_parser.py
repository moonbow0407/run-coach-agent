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
    text = raw.strip()
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
