"""ID 生成：统一入口，便于将来更换 ID 策略或加埋点。"""

from uuid import UUID, uuid4


def new_id() -> UUID:
    """生成一个新 UUID（v4）。"""
    return uuid4()
