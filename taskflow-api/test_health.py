"""Focused tests for the database-aware GET /health endpoint.

These tests override the request-scoped database dependency, so the real
development database is never opened or modified.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db

HEALTHY_BODY = {
    "status": "healthy",
    "message": "TaskFlow api is running",
    "database": "connected",
}
UNHEALTHY_BODY = {
    "status": "unhealthy",
    "message": "TaskFlow api is running",
    "database": "unavailable",
}


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated disposable SQLite database for health tests."""
    database = tmp_path / "health-test.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        engine.dispose()


@contextmanager
def make_client(dependency):
    """Build a TestClient with an overridden database dependency.

    The client is not entered as a context manager because that would run the
    application lifespan and initialize the real development database.
    """
    main.app.dependency_overrides[get_db] = dependency
    client = TestClient(main.app)
    try:
        yield client
    finally:
        client.close()
        main.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def healthy_client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with make_client(override_get_db) as client:
        yield client


@pytest.fixture
def failing_session():
    """A session whose query fails with a realistic, sensitive error."""
    session = MagicMock()
    session.execute.side_effect = OperationalError(
        "SELECT 1",
        {},
        Exception(
            "connection to postgresql://taskflow:super-secret-password@db "
            "failed: server closed the connection unexpectedly"
        ),
    )
    return session


@pytest.fixture
def unhealthy_client(failing_session):
    def override_get_db():
        yield failing_session

    with make_client(override_get_db) as client:
        yield client


def test_health_reports_healthy_when_database_reachable(healthy_client):
    response = healthy_client.get("/health")

    assert response.status_code == 200
    assert response.json() == HEALTHY_BODY


def test_health_is_not_authenticated(healthy_client):
    """No Authorization header is needed and no credentials are involved."""
    response = healthy_client.get("/health")

    assert response.status_code == 200
    assert "authorization" not in {
        name.lower() for name in response.request.headers
    }


def test_health_reports_503_when_database_fails(unhealthy_client):
    response = unhealthy_client.get("/health")

    assert response.status_code == 503
    assert response.json() == UNHEALTHY_BODY


def test_health_failure_rolls_back_failed_transaction(
    unhealthy_client,
    failing_session,
):
    unhealthy_client.get("/health")

    failing_session.rollback.assert_called_once_with()


def test_health_failure_response_does_not_leak_internals(unhealthy_client):
    response = unhealthy_client.get("/health")
    body = response.text.lower()

    assert response.status_code == 503
    for secret_or_internal in (
        "postgresql://",
        "super-secret-password",
        "taskflow:",
        "select 1",
        "operationalerror",
        "traceback",
        "password",
        "exception",
        "connection string",
    ):
        assert secret_or_internal not in body


def test_health_still_returns_503_when_rollback_fails():
    """A secondary rollback error must not turn the health response into 500."""
    session = MagicMock()
    session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("connection lost")
    )
    session.rollback.side_effect = OperationalError(
        "ROLLBACK", {}, Exception("connection already closed")
    )

    def override_get_db():
        yield session

    with make_client(override_get_db) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == UNHEALTHY_BODY
