"""序列化边界保留合法结构，拒绝未知对象。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

import pytest
from pydantic import BaseModel

from app.infrastructure.jsonutil import json_ready


class Kind(Enum):
    RUN = "run"


@dataclass(slots=True)
class Workout:
    id: UUID
    recorded_at: datetime
    kind: Kind


class Envelope(BaseModel):
    count: int


def test_nested_domain_values_remain_structured() -> None:
    uid = UUID(int=1)
    now = datetime(2026, 10, 2, tzinfo=UTC)
    assert json_ready({"workouts": (Workout(uid, now, Kind.RUN),), "meta": Envelope(count=1)}) == {
        "workouts": [{"id": str(uid), "recorded_at": now.isoformat(), "kind": "run"}],
        "meta": {"count": 1},
    }


@pytest.mark.parametrize("value", [object(), {"nested": [object()]}, Workout, {1, 2}])
def test_unknown_values_fail_instead_of_becoming_text(value: object) -> None:
    with pytest.raises(TypeError, match="不支持的 JSON 类型"):
        json_ready(value)


@pytest.mark.parametrize("value", [{object(): "value"}, {1: "a", "1": "b"}])
def test_dictionary_keys_are_not_silently_coerced(value: object) -> None:
    with pytest.raises(TypeError, match="键必须是字符串"):
        json_ready(value)
