"""反馈量表领域校验：1-10 之外的主观评分必须被拒绝。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.coaching.domain.workout.models import WorkoutFeedback
from app.common.errors import DomainError


def test_subjective_scale_rejects_out_of_range() -> None:
    """验证：sRPE 填 11 越界时构造 WorkoutFeedback 抛 DomainError。"""
    now = datetime.now(UTC)
    # pytest.raises：断言构造过程抛出领域错误，而非静默截断
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
