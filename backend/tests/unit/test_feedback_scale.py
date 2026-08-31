from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.coaching.domain.workout.models import WorkoutFeedback
from app.common.errors import DomainError


def test_subjective_scale_rejects_out_of_range() -> None:
    now = datetime.now(UTC)
    with pytest.raises(DomainError):
        WorkoutFeedback(
            id=uuid4(),
            user_id=uuid4(),
            workout_id=uuid4(),
            perceived_exertion=11,
            subjective_fatigue=None,
            soreness=None,
            note=None,
            created_at=now,
            updated_at=now,
        )
