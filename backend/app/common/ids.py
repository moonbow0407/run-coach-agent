"""ID 生成：统一入口，便于将来更换 ID 策略或加埋点。"""

from uuid import UUID

from uuid_utils.compat import uuid7


def new_id() -> UUID:
    """生成时间有序的 UUIDv7，ID 前缀即创建毫秒时间戳。

    有序 ID 可改善数据库 B-tree 插入局部性，并让字典序即时间序、便于排查。
    """
    return uuid7()
