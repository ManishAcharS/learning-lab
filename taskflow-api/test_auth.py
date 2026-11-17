"""Tests for user registration and authentication endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from models import User
from security import verify_password


@pytest.fixture
def auth_session_factory(tmp_path):
    """Create an isolated temporary SQLite database for auth tests."""
    test_database = tmp_path / "test_auth.db"
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
def auth_client(auth_session_factory):
    """Test client overriding get_db with the isolated auth database."""
    def override_get_db():
        session = auth_session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(main.app)
    try:
        yield test_client
    finally:
        test_client.close()
        main.app.dependency_overrides.pop(get_db, None)


def test_successful_user_registration(auth_client, auth_session_factory):
    payload = {
        "email": "user@example.com",
        "password": "SuperSecretPassword123!",
    }
    response = auth_client.post("/auth/register", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"
    assert "id" in data
    assert isinstance(data["id"], int)
    assert "created_at" in data

    # Response must NEVER expose password or hashed_password
    assert "password" not in data
    assert "hashed_password" not in data
    assert set(data.keys()) == {"id", "email", "created_at"}

    # Verify database persistence and password hashing
    with auth_session_factory() as session:
        user = session.scalar(select(User).where(User.email == "user@example.com"))
        assert user is not None
        assert user.hashed_password != payload["password"]
        assert payload["password"] not in user.hashed_password
        assert user.hashed_password.startswith("$argon2id$")
        assert verify_password(payload["password"], user.hashed_password) is True


def test_registration_normalizes_email(auth_client, auth_session_factory):
    payload = {
        "email": "  MixedCase.User@EXAMPLE.COM  ",
        "password": "SuperSecretPassword123!",
    }
    response = auth_client.post("/auth/register", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "mixedcase.user@example.com"

    with auth_session_factory() as session:
        user = session.scalar(select(User).where(User.id == data["id"]))
        assert user is not None
        assert user.email == "mixedcase.user@example.com"


def test_duplicate_email_registration_returns_409(auth_client):
    payload = {
        "email": "duplicate@example.com",
        "password": "FirstPassword123!",
    }
    first_response = auth_client.post("/auth/register", json=payload)
    assert first_response.status_code == 201

    # Attempting to register the exact same email returns 409 Conflict
    second_response = auth_client.post(
        "/auth/register",
        json={"email": "duplicate@example.com", "password": "SecondPassword123!"},
    )
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Email already registered"

    # Attempting to register the same email with different casing/whitespace also returns 409
    third_response = auth_client.post(
        "/auth/register",
        json={"email": "  DUPLICATE@example.com  ", "password": "ThirdPassword123!"},
    )
    assert third_response.status_code == 409
    assert third_response.json()["detail"] == "Email already registered"


@pytest.mark.parametrize(
    "invalid_email",
    [
        "not-an-email",
        "@missingusername.com",
        "missingdomain@",
        "spaces in@email.com",
        "",
    ],
)
def test_registration_rejects_invalid_email(auth_client, invalid_email):
    response = auth_client.post(
        "/auth/register",
        json={"email": invalid_email, "password": "ValidPassword123!"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "invalid_password",
    [
        "short",  # < 8 chars
        "",  # empty
        "        ",  # whitespace only
        "a" * 129,  # exceeds max length
    ],
)
def test_registration_rejects_invalid_password(auth_client, invalid_password):
    response = auth_client.post(
        "/auth/register",
        json={"email": "valid@example.com", "password": invalid_password},
    )
    assert response.status_code == 422
