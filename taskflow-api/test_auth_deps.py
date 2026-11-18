"""Tests for the authenticated-user dependency and ``GET /auth/me``."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import User
from security import create_access_token, hash_password

# Test-only credentials. Production code loads its key from the environment.
TEST_SECRET = (
    "test-only-auth-deps-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
OTHER_TEST_SECRET = (
    "test-only-different-auth-deps-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_PASSWORD = "SuperSecretPassword123!"


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key without relying on real credentials."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database for auth dependency tests."""
    test_database = tmp_path / "test_auth_deps.db"
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
def client(session_factory):
    """Test client backed by the fixture's temporary database."""

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
    test_client = TestClient(main.app)
    try:
        yield test_client
    finally:
        test_client.close()
        main.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def create_user(session_factory):
    """Insert a registered user into the temporary database."""

    def _create_user(email: str, password: str = TEST_PASSWORD) -> User:
        with session_factory() as session:
            user = User(
                email=email,
                hashed_password=hash_password(password),
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            session.expunge(user)
            return user

    return _create_user


@pytest.fixture
def user(create_user):
    return create_user("alice@example.com")


def bearer_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def token_for(
    user_id: int,
    *,
    secret: str = TEST_SECRET,
    expires_delta: timedelta | None = None,
) -> str:
    return create_access_token(
        str(user_id),
        secret,
        expires_delta=expires_delta,
    )


def assert_unauthorized(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


def test_missing_token_returns_401(client):
    assert_unauthorized(client.get("/auth/me"))


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", "header.payload.signature"])
def test_malformed_token_returns_401(client, token):
    assert_unauthorized(client.get("/auth/me", headers=bearer_header(token)))


def test_non_bearer_authorization_returns_401(client, user):
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Basic {token_for(user.id)}"},
    )

    assert_unauthorized(response)


def test_tampered_token_returns_401(client, user):
    token = token_for(user.id)
    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    assert_unauthorized(client.get("/auth/me", headers=bearer_header(tampered)))


def test_expired_token_returns_401(client, user):
    token = token_for(user.id, expires_delta=timedelta(minutes=-5))

    assert_unauthorized(client.get("/auth/me", headers=bearer_header(token)))


def test_token_signed_with_wrong_secret_returns_401(client, user):
    token = token_for(user.id, secret=OTHER_TEST_SECRET)

    assert_unauthorized(client.get("/auth/me", headers=bearer_header(token)))


@pytest.mark.parametrize(
    "invalid_subject",
    ["not-a-user-id", "alice@example.com", "0", "-1", "1.5", "9" * 20],
)
def test_invalid_subject_returns_401(client, invalid_subject):
    token = create_access_token(invalid_subject, TEST_SECRET)

    assert_unauthorized(client.get("/auth/me", headers=bearer_header(token)))


def test_token_for_nonexistent_user_returns_401(client):
    token = token_for(999_999)

    assert_unauthorized(client.get("/auth/me", headers=bearer_header(token)))


def test_valid_token_returns_authenticated_user(client, user):
    response = client.get("/auth/me", headers=bearer_header(token_for(user.id)))

    assert response.status_code == 200
    assert response.json()["id"] == user.id
    assert response.json()["email"] == user.email


def test_auth_me_returns_only_safe_user_fields(client, user):
    response = client.get("/auth/me", headers=bearer_header(token_for(user.id)))

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == user.email
    assert "created_at" in data
    assert set(data) == {"id", "email", "created_at"}
    assert "password" not in data
    assert "hashed_password" not in data
    assert user.hashed_password not in response.text


def test_request_identity_inputs_cannot_impersonate_another_user(
    client,
    create_user,
):
    alice = create_user("alice@example.com")
    bob = create_user("bob@example.com")

    response = client.request(
        "GET",
        "/auth/me",
        params={"user_id": bob.id, "id": bob.id, "email": bob.email},
        json={"user_id": bob.id, "id": bob.id, "email": bob.email},
        headers={
            **bearer_header(token_for(alice.id)),
            "X-User-Id": str(bob.id),
            "X-User-Email": bob.email,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == alice.id
    assert data["email"] == alice.email
    assert data["id"] != bob.id
    assert bob.hashed_password not in response.text


def test_missing_jwt_configuration_fails_closed(client, user, monkeypatch):
    monkeypatch.delenv(JWT_SECRET_ENV_VAR, raising=False)
    token = token_for(user.id)

    response = client.get("/auth/me", headers=bearer_header(token))

    assert response.status_code == 500
    assert response.json() == {"detail": "Authentication is not configured"}
