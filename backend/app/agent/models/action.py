from typing import Any, Literal

from pydantic import BaseModel, Field


class CapabilityCallAction(BaseModel):
    type: Literal["capability_call"] = "capability_call"
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class FinalAction(BaseModel):
    type: Literal["final"] = "final"
    content: str


AgentAction = CapabilityCallAction | FinalAction
