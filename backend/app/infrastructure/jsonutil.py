from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID


def json_ready(value: Any) -> Any:
    """把领域对象转成 JSONB / Observation 可序列化结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_ready(value.model_dump())
    if hasattr(value, "__dataclass_fields__"):
        return json_ready(vars(value))
    return str(value)
