"""用户领域模型。Phase 1 用户无个人属性字段，身份由认证承载。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class User:
    id: UUID
    created_at: datetime
    updated_at: datetime
