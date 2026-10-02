"""场景测试入口。真实 seed 实现位于 infrastructure，避免测试自己再写一份数据。"""

from app.infrastructure.seed.vertical_slice import VerticalSliceSeed, seed_vertical_slice

__all__ = ["VerticalSliceSeed", "seed_vertical_slice"]
