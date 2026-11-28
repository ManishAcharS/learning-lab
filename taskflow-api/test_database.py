"""Tests for database engine, session, and startup helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import database


def test_create_database_engine_sqlite_connects_and_selects(tmp_path):
    """SQLite engines keep the thread-sharing option and are usable."""
    database_path = tmp_path / "engine-test.db"
    engine = database.create_database_engine(
        f"sqlite:///{database_path.as_posix()}"
    )

    try:
        assert engine.dialect.name == "sqlite"
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar() == 1
    finally:
        engine.dispose()


def test_create_database_engine_uses_pre_ping_for_non_sqlite(monkeypatch):
    """Non-SQLite engines enable pool_pre_ping so stale sockets are replaced."""
    calls = {}
    sentinel = object()

    def fake_create_engine(database_url, **kwargs):
        calls["url"] = database_url
        calls["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(database, "create_engine", fake_create_engine)

    result = database.create_database_engine(
        "postgresql+psycopg://user:test-only@db:5432/taskflow"
    )

    assert result is sentinel
    assert calls["url"].startswith("postgresql+psycopg://")
    assert calls["kwargs"] == {"pool_pre_ping": True}


def test_sqlite_listener_enables_foreign_keys(monkeypatch):
    """The connect listener must execute the SQLite foreign-key pragma."""
    executed = []
    cursor = MagicMock()
    cursor.execute.side_effect = executed.append
    connection = MagicMock()
    connection.cursor.return_value = cursor

    monkeypatch.setattr(
        database,
        "engine",
        SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
    )

    database._enable_sqlite_foreign_keys(connection, None)

    assert executed == ["PRAGMA foreign_keys=ON"]
    cursor.close.assert_called_once_with()


def test_sqlite_listener_is_a_noop_for_postgresql(monkeypatch):
    """PostgreSQL enforces foreign keys itself, so no pragma is issued."""
    connection = MagicMock()

    monkeypatch.setattr(
        database,
        "engine",
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )

    database._enable_sqlite_foreign_keys(connection, None)

    connection.cursor.assert_not_called()


def test_get_db_yields_a_session_and_closes_it(monkeypatch):
    """A successful request session is always closed, not rolled back."""
    session = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    generator = database.get_db()
    assert next(generator) is session

    generator.close()

    session.close.assert_called_once_with()
    session.rollback.assert_not_called()


def test_get_db_rolls_back_and_reraises_on_error(monkeypatch):
    """A failing request must roll back, propagate, and still close."""
    session = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    generator = database.get_db()
    assert next(generator) is session

    with pytest.raises(RuntimeError, match="request failed"):
        generator.throw(RuntimeError("request failed"))

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_init_db_creates_all_registered_tables(monkeypatch):
    """Startup creates missing tables against the configured engine."""
    engine = MagicMock()
    create_all = MagicMock()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.Base.metadata, "create_all", create_all)

    database.init_db()

    create_all.assert_called_once_with(bind=engine)
