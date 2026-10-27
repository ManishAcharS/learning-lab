"""Database configuration and request-scoped sessions for TaskFlow."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = PROJECT_DIR / "taskflow.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"


class Base(DeclarativeBase):
    """Base class shared by all SQLAlchemy ORM models."""


# check_same_thread=False allows FastAPI's thread pool to share connections
# while each request still gets its own session.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield one session per request and always close it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables during application startup.

    ``create_all`` only creates missing tables. It does not add or alter
    columns on an existing table, so real schema changes need a migration.
    """
    # Import the model so its table is registered on Base.metadata.
    from models import Task  # noqa: F401

    Base.metadata.create_all(bind=engine)
