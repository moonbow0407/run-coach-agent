from datetime import datetime, timezone
from uuid import uuid4

from app.agent.lifecycle.events import TurnCommitted, event_as_log_fields


def test_turn_committed_value_semantics() -> None:
    event = TurnCommitted(
        request_id=uuid4(),
        turn_id=uuid4(),
        thread_id=uuid4(),
        user_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        run_id=uuid4(),
        committed_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    fields = event_as_log_fields(event)
    assert fields["event_type"] == "TurnCommitted"
    assert fields["turn_id"] == str(event.turn_id)
    assert "assistant_message_id" in fields
