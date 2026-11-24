"""Strict task validation and standardized 422 response tests."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import User
from security import create_access_token, hash_password

TEST_SECRET = (
    "test-only-task-validation-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_EMAIL = "validation@example.com"
TEST_PASSWORD = "SuperSecretPassword123!"


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key without relying on real credentials."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database for validation tests."""
    test_database = tmp_path / "test_task_validation.db"
    test_engine = create_engine(
        f"sqlite:///{test_database.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=test_engine)

    try:
        yield TestingSessionLocal
    finally:
        test_engine.dispose()


@pytest.fixture
def user_id(session_factory):
    """Insert the authenticated task owner."""
    with session_factory() as session:
        user = User(
            email=TEST_EMAIL,
            hashed_password=hash_password(TEST_PASSWORD),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


@pytest.fixture
def client(session_factory, user_id):
    """Authenticated TestClient backed by the temporary database."""

    def override_get_db():
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(str(user_id), TEST_SECRET)
    test_client = TestClient(
        main.app,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        yield test_client
    finally:
        test_client.close()
        main.app.dependency_overrides.pop(get_db, None)


def assert_validation_error(response, expected_fields: set[str]) -> dict:
    """Check the public 422 contract and return the decoded payload."""
    assert response.status_code == 422
    payload = response.json()
    assert set(payload) == {"error", "fields"}
    assert payload["error"] == "validation_error"
    assert isinstance(payload["fields"], list)

    actual_fields = set()
    for error in payload["fields"]:
        assert set(error) == {"field", "message"}
        assert isinstance(error["field"], str) and error["field"]
        assert isinstance(error["message"], str) and error["message"]
        actual_fields.add(error["field"])

    assert expected_fields <= actual_fields
    return payload


def test_empty_title_returns_standard_validation_error(client):
    response = client.post("/tasks", json={"title": ""})

    assert_validation_error(response, {"title"})


def test_whitespace_only_title_returns_standard_validation_error(client):
    response = client.post("/tasks", json={"title": " \t\n "})

    assert_validation_error(response, {"title"})


def test_description_over_2000_characters_is_rejected(client):
    response = client.post(
        "/tasks",
        json={"title": "Valid title", "description": "x" * 2001},
    )

    assert_validation_error(response, {"description"})


def test_invalid_status_is_rejected(client):
    response = client.post(
        "/tasks",
        json={"title": "Valid title", "status": "archived"},
    )

    assert_validation_error(response, {"status"})


def test_past_due_date_is_rejected(client):
    yesterday = date.today() - timedelta(days=1)

    response = client.post(
        "/tasks",
        json={"title": "Valid title", "due_date": yesterday.isoformat()},
    )

    assert_validation_error(response, {"due_date"})


def test_todays_due_date_is_accepted(client):
    today = date.today()

    response = client.post(
        "/tasks",
        json={"title": "Due today", "due_date": today.isoformat()},
    )

    assert response.status_code == 201
    assert response.json()["due_date"] == today.isoformat()


def test_valid_task_creation_still_returns_201(client):
    today = date.today()
    response = client.post(
        "/tasks",
        json={
            "title": "x" * 120,
            "description": "d" * 2000,
            "status": "completed",
            "due_date": today.isoformat(),
        },
    )

    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "x" * 120
    assert created["description"] == "d" * 2000
    assert created["status"] == "completed"
    assert created["completed"] is True
    assert created["due_date"] == today.isoformat()


def test_multiple_invalid_fields_produce_multiple_errors(client):
    yesterday = date.today() - timedelta(days=1)

    response = client.post(
        "/tasks",
        json={
            "title": "   ",
            "description": "x" * 2001,
            "status": "archived",
            "due_date": yesterday.isoformat(),
        },
    )

    payload = assert_validation_error(
        response,
        {"title", "description", "status", "due_date"},
    )
    assert len(payload["fields"]) >= 4


def test_validation_response_does_not_leak_internals_or_values(client):
    sensitive_value = "sensitive-request-value"

    response = client.post(
        "/tasks",
        json={
            "title": "Valid title",
            "description": sensitive_value * 200,
            "status": "not-a-real-status",
        },
    )

    assert_validation_error(response, {"description", "status"})
    body = response.text
    assert sensitive_value not in body
    assert "Traceback" not in body
    assert "RequestValidationError" not in body
    assert "pydantic" not in body.lower()
    assert "input" not in response.json()


def test_query_validation_uses_the_same_response_shape(client):
    response = client.get("/tasks", params={"limit": 0})

    assert_validation_error(response, {"limit"})


def test_path_validation_uses_the_same_response_shape(client):
    response = client.get("/tasks/not-an-integer")

    assert_validation_error(response, {"task_id"})


def test_update_rejects_a_past_due_date(client):
    created = client.post("/tasks", json={"title": "Patch me"}).json()
    yesterday = date.today() - timedelta(days=1)

    response = client.patch(
        f"/tasks/{created['id']}",
        json={"due_date": yesterday.isoformat()},
    )

    assert_validation_error(response, {"due_date"})


def test_update_accepts_todays_due_date_and_status(client):
    created = client.post("/tasks", json={"title": "Patch me"}).json()
    today = date.today()

    response = client.patch(
        f"/tasks/{created['id']}",
        json={"due_date": today.isoformat(), "status": "completed"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["due_date"] == today.isoformat()
    assert updated["status"] == "completed"
    assert updated["completed"] is True
