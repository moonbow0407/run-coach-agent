"""本地签发 JWT，不作为公开 API。

用法（在 backend/ 目录）:
    python scripts/issue_token.py <user_id>
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.auth.jwt import issue_token
from app.infrastructure.config import Settings


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/issue_token.py <user_id>")
    user_id = UUID(sys.argv[1])
    settings = Settings()
    token = issue_token(
        user_id=user_id,
        secret=settings.jwt_secret,
        now=datetime.now(timezone.utc),
        expire_seconds=settings.jwt_expire_seconds,
        algorithm=settings.jwt_algorithm,
    )
    print(token)


if __name__ == "__main__":
    main()
