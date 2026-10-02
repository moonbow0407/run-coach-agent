"""本地签发 JWT，不作为公开 API。

用法（在 backend/ 目录）:
    python scripts/issue_token.py <user_id>
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

# 把仓库根目录加入导入路径，使脚本可直接运行。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.auth.jwt import issue_token
from app.infrastructure.config import Settings


def main() -> None:
    """解析命令行参数，为指定用户签发 JWT 并打印。"""
    # 参数数量不对立即退出并提示用法（fail fast）。
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/issue_token.py <user_id>")
    user_id = UUID(sys.argv[1])
    settings = Settings()
    token = issue_token(
        user_id=user_id,
        secret=settings.jwt_secret,
        now=datetime.now(UTC),
        expire_seconds=settings.jwt_expire_seconds,
        algorithm=settings.jwt_algorithm,
    )
    # 令牌打印到 stdout，供 curl / 前端联调时携带认证。
    print(token)


if __name__ == "__main__":
    main()
