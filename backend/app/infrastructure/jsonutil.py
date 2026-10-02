"""通用 JSON 序列化：把领域对象（dataclass / Pydantic / 枚举 / UUID 等）
转为可写入 JSONB 或放进 Observation 的纯结构。
"""

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


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
        return json_ready(value.value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON 对象的键必须是字符串")
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, BaseModel):
        return json_ready(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: json_ready(getattr(value, field.name)) for field in fields(value)}
    raise TypeError(f"不支持的 JSON 类型: {type(value).__name__}")
