"""Turn 终态事件转结构化日志字段的可观测性契约。"""

from datetime import UTC, datetime
from uuid import uuid4

from app.agent.lifecycle.events import TurnCommitted, event_as_log_fields


def test_turn_committed_value_semantics() -> None:
    """验证：TurnCommitted 可展开为日志字段，UUID 序列化为字符串且关键 id 齐全。"""
    event = TurnCommitted(
        request_id=uuid4(),
        trace_id=uuid4(),
        turn_id=uuid4(),
        thread_id=uuid4(),
        user_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        run_id=uuid4(),
        committed_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    fields = event_as_log_fields(event)
    assert fields["event_type"] == "TurnCommitted"
    assert fields["turn_id"] == str(event.turn_id)
    assert "assistant_message_id" in fields
