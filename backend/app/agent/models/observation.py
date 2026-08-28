from typing import Any, Literal

from pydantic import BaseModel


class Observation(BaseModel):
    source: str
    status: Literal["success", "error"]
    data: Any | None = None
    error: str | None = None
