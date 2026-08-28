import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings


def test_jwt_secret_must_have_at_least_32_characters() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret="too-short")
