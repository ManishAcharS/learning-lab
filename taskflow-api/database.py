"""Database configuration and request-scoped sessions for TaskFlow."""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = PROJECT_DIR / "taskflow.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# ``DATABASE_URL`` lets containers and other deployments point the application
# at PostgreSQL. Local development keeps using the existing SQLite file when
# the variable is unset, so no extra setup is required.
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


class Base(DeclarativeBase):
    """Base class shared by all SQLAlchemy ORM models."""


def create_database_engine(database_url: str) -> Engine:
    """Create an engine with the options required by the target dialect."""
    if database_url.startswith("sqlite"):
        # check_same_thread=False allows FastAPI's thread pool to share
        # connections while each request still gets its own session.
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

    # Recycle stale connections instead of handing a dead socket to a request,
    # which also lets the health check recover after PostgreSQL restarts.
    return create_engine(database_url, pool_pre_ping=True)


engine = create_database_engine(DATABASE_URL)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """Make SQLite enforce foreign keys, including ON DELETE CASCADE.

    SQLite disables foreign-key enforcement per connection by default, so
    without this pragma the database-level cascades declared by the models and
    migrations would not run. PostgreSQL always enforces them, so this listener
    only attaches when the configured URL uses SQLite.
    """
    if engine.dialect.name != "sqlite":
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield one request-scoped session and always clean it up afterward."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Roll back any pending work, then re-raise so the error is not hidden.
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables during application startup.

    ``create_all`` only creates missing tables. It does not add or alter
    columns on an existing table, so real schema changes need a migration.
    """
    # Import models so their tables are registered on Base.metadata.
    from models import Comment, Task, User  # noqa: F401

    Base.metadata.create_all(bind=engine)
