"""SQLAlchemy 声明基类：所有 ORM Row 的公共父类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
