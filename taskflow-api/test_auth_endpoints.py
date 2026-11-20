"""Tests for the OAuth2 password-form login endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import User
from security import decode_access_token, hash_password

# Test-only credentials. Production code loads its key from the environment.
TEST_SECRET = (
    "test-only-auth-endpoints-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_EMAIL = "alice@example.com"
TEST_PASSWORD = "SuperSecretPassword123!"


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key without relying on real credentials."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database for login tests."""
    test_database = tmp_path / "test_auth_endpoints.db"
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

    def _create_user(
        email: str = TEST_EMAIL,
        password: str = TEST_PASSWORD,
    ) -> User:
        with session_factory() as session:
            user = User(
                email=email.strip().lower(),
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
    return create_user()


def login(client, username=TEST_EMAIL, password=TEST_PASSWORD):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )


def bearer_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_invalid_credentials(response) -> None:
    """Unknown email and wrong password must be indistinguishable."""
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Incorrect email or password"}
    assert "access_token" not in response.text


def test_registered_user_can_log_in(client, user):
    response = login(client)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_successful_login_returns_access_token(client, user):
    response = login(client)

    assert response.status_code == 200
    assert isinstance(response.json()["access_token"], str)
    assert response.json()["access_token"]


def test_successful_login_returns_bearer_token_type(client, user):
    response = login(client)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_issued_jwt_decodes_with_existing_utility(client, user):
    token = login(client).json()["access_token"]

    payload = decode_access_token(token, TEST_SECRET)

    assert set(payload) == {"sub", "iat", "exp"}


def test_jwt_subject_is_the_user_id(client, user):
    token = login(client).json()["access_token"]

    payload = decode_access_token(token, TEST_SECRET)

    assert payload["sub"] == str(user.id)
    assert payload["sub"].isdecimal()


def test_login_normalizes_email_like_registration(client, user):
    response = login(client, username="  ALICE@Example.COM  ")

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_registered_user_can_log_in_through_registration_flow(client):
    payload = {
        "email": "  New.User@Example.COM  ",
        "password": "AnotherSecretPassword123!",
    }
    registration = client.post("/auth/register", json=payload)
    assert registration.status_code == 201

    response = login(
        client,
        username="NEW.USER@example.com",
        password=payload["password"],
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    profile = client.get("/auth/me", headers=bearer_header(token))

    assert profile.status_code == 200
    assert profile.json()["id"] == registration.json()["id"]


def test_incorrect_password_returns_401(client, user):
    assert_invalid_credentials(login(client, password="WrongPassword123!"))


def test_unknown_email_returns_the_same_401(client, user):
    assert_invalid_credentials(login(client, username="nobody@example.com"))


def test_unknown_email_and_wrong_password_are_indistinguishable(client, user):
    unknown = login(client, username="nobody@example.com")
    wrong_password = login(client, password="WrongPassword123!")

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()
    assert (
        unknown.headers["www-authenticate"]
        == wrong_password.headers["www-authenticate"]
        == "Bearer"
    )


def test_unknown_email_does_not_issue_a_token(client, user):
    response = login(client, username="nobody@example.com")

    assert "access_token" not in response.text


@pytest.mark.parametrize(
    "form_data",
    [
        {"password": TEST_PASSWORD},
        {"username": TEST_EMAIL},
        {},
    ],
    ids=["missing-username", "missing-password", "missing-both"],
)
def test_missing_form_fields_are_rejected(client, user, form_data):
    response = client.post("/auth/login", data=form_data)

    assert response.status_code == 422


def test_login_response_never_exposes_hashed_password(client, user):
    response = login(client)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"access_token", "token_type"}
    assert "hashed_password" not in data
    assert user.hashed_password not in response.text


def test_login_response_never_exposes_the_submitted_password(client, user):
    response = login(client)

    assert response.status_code == 200
    assert TEST_PASSWORD not in response.text
    assert "password" not in response.json()


def test_issued_token_works_with_protected_auth_me(client, user):
    token = login(client).json()["access_token"]

    response = client.get("/auth/me", headers=bearer_header(token))

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == user.email
    assert "hashed_password" not in data


def test_openapi_documents_the_login_token_url(client):
    scheme = main.app.openapi()["components"]["securitySchemes"]["OAuth2PasswordBearer"]

    assert scheme["type"] == "oauth2"
    assert scheme["flows"]["password"]["tokenUrl"] == "/auth/login"
