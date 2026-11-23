"""Tests for per-IP rate limiting on the login endpoint.

Every test gets a fresh temporary database and a controlled TestClient peer IP.
The autouse limiter-reset fixture in ``conftest.py`` isolates in-memory counters
between tests, so these tests never sleep or depend on execution order.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import User
from security import hash_password

# Test-only signing key. Production code reads TASKFLOW_JWT_SECRET.
TEST_SECRET = (
    "test-only-rate-limit-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_EMAIL = "rate-limit@example.com"
TEST_PASSWORD = "SuperSecretPassword123!"
ALLOWED_REQUESTS = 5
RATE_LIMIT_DETAIL = "Rate limit exceeded"


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key without relying on real credentials."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database for rate-limit tests."""
    test_database = tmp_path / "test_rate_limit.db"
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
def user(session_factory):
    """Insert one valid user directly into the temporary database."""
    with session_factory() as session:
        account = User(
            email=TEST_EMAIL,
            hashed_password=hash_password(TEST_PASSWORD),
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        session.expunge(account)
        return account


@pytest.fixture
def client_factory(session_factory):
    """Build TestClients with explicit peer IP addresses.

    SlowAPI identifies clients from ``request.client.host``, so passing a
    ``(host, port)`` tuple to TestClient exercises the real key function rather
    than relying on a forwarded header.
    """

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
    clients: list[TestClient] = []

    def make_client(host: str) -> TestClient:
        test_client = TestClient(
            main.app,
            client=(host, 50000),
        )
        clients.append(test_client)
        return test_client

    try:
        yield make_client
    finally:
        for test_client in clients:
            test_client.close()
        main.app.dependency_overrides.pop(get_db, None)


def login(
    client: TestClient,
    *,
    username: str = TEST_EMAIL,
    password: str = TEST_PASSWORD,
    headers: dict[str, str] | None = None,
):
    """Submit the same OAuth2 password form used by the real application."""
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        headers=headers,
    )


def exhaust_login_limit(client: TestClient) -> None:
    """Use exactly the five requests that are allowed in one window."""
    for _ in range(ALLOWED_REQUESTS):
        response = login(client)
        assert response.status_code == 200


def test_five_login_requests_from_one_ip_are_allowed(client_factory, user):
    client = client_factory("198.51.100.10")

    responses = [login(client) for _ in range(ALLOWED_REQUESTS)]

    assert [response.status_code for response in responses] == [200] * 5
    assert all(response.json()["token_type"] == "bearer" for response in responses)
    assert all(response.json()["access_token"] for response in responses)


def test_sixth_login_request_from_one_ip_returns_429(client_factory, user):
    client = client_factory("198.51.100.11")
    exhaust_login_limit(client)

    response = login(client)

    assert response.status_code == 429


def test_rate_limit_response_has_a_valid_retry_after_header(client_factory, user):
    client = client_factory("198.51.100.12")
    exhaust_login_limit(client)

    response = login(client)

    assert response.status_code == 429
    retry_after = response.headers["Retry-After"]
    assert retry_after.isdecimal()
    assert 0 < int(retry_after) <= 60


def test_rate_limit_response_has_the_consistent_json_body(client_factory, user):
    client = client_factory("198.51.100.13")
    exhaust_login_limit(client)

    response = login(client)

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": RATE_LIMIT_DETAIL}


def test_another_client_ip_has_an_independent_rate_limit(client_factory, user):
    first_ip = client_factory("198.51.100.14")
    second_ip = client_factory("198.51.100.15")

    exhaust_login_limit(first_ip)
    assert login(first_ip).status_code == 429
    exhaust_login_limit(second_ip)
    assert login(second_ip).status_code == 429


def test_valid_login_within_the_limit_still_succeeds(client_factory, user):
    client = client_factory("198.51.100.16")

    response = login(client)

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]

    profile = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == TEST_EMAIL


def test_existing_login_failures_are_unchanged_below_the_limit(
    client_factory,
    user,
):
    client = client_factory("198.51.100.17")

    wrong_password = login(client, password="WrongPassword123!")
    unknown_email = login(client, username="nobody@example.com")

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {"detail": "Incorrect email or password"}


def test_forwarded_ip_header_does_not_bypass_the_real_client_ip(
    client_factory,
    user,
):
    client = client_factory("198.51.100.18")

    for index in range(ALLOWED_REQUESTS):
        response = login(
            client,
            headers={"X-Forwarded-For": f"203.0.113.{index}"},
        )
        assert response.status_code == 200

    response = login(
        client,
        headers={"X-Forwarded-For": "203.0.113.99"},
    )

    assert response.status_code == 429


def test_unrelated_endpoints_are_not_rate_limited(client_factory):
    client = client_factory("198.51.100.19")

    responses = [client.get("/health") for _ in range(10)]

    assert [response.status_code for response in responses] == [200] * 10
