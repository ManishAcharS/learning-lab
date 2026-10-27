"""SQLAlchemy ORM models for TaskFlow."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Task(Base):
    """A task persisted in the ``tasks`` table."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "length(title) BETWEEN 1 AND 100",
            name="ck_tasks_title_length",
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
