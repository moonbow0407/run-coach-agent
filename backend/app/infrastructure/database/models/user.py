"""用户表：Phase 1 只有主键与时间戳，认证信息由 JWT 承载。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
