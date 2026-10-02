"""有上限的 retry schedule；jitter 由稳定 identity 决定。"""

import hashlib
from datetime import timedelta
from uuid import UUID

# 重试退避档位：第 n 次重试取第 n 档，超出后固定用最后一档（6 小时）。
RETRY_DELAYS = (
    timedelta(seconds=5),
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
)
MAX_ATTEMPTS = 8  # 最大尝试次数（含首次），耗尽即判死信


def retry_delay(*, attempt: int, event_id: UUID) -> timedelta:
    """计算第 attempt 次重试的延迟：固定退避档位 + 由事件 ID 决定的确定性抖动。"""
    # 参数非法直接报错（fail fast）。
    if attempt <= 0:
        raise ValueError("attempt_must_be_positive")
    base = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
    digest = hashlib.sha256(f"{event_id}:{attempt}".encode()).digest()
    # 0–20% bounded deterministic jitter，既避免惊群又保持测试可复现。
    jitter_ratio = int.from_bytes(digest[:2]) / 65535 * 0.20
    return base + timedelta(seconds=base.total_seconds() * jitter_ratio)
