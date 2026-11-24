"""End-to-end integration tests for registration, login, JWT auth, and tasks.

Every test gets its own temporary SQLite database and a real FastAPI TestClient
whose ``get_db`` dependency is overridden. The production ``taskflow.db`` is
never opened. Users and tokens are created through the real registration and
login endpoints so the complete authentication chain is exercised.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import main
from database import DATABASE_PATH, Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import Task, User
from security import (
    create_access_token,
    decode_access_token,
    verify_password,
)

# Test-only signing key. Production code reads TASKFLOW_JWT_SECRET.
TEST_SECRET = (
    "test-only-auth-integration-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
OTHER_TEST_SECRET = (
    "test-only-different-auth-integration-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)

TEST_PASSWORD = "SuperSecretPassword123!"
UNAUTHENTICATED_DETAIL = "Could not validate credentials"
LOGIN_ERROR_DETAIL = "Incorrect email or password"
OWNERSHIP_ERROR_DETAIL = "Not authorized to access this task"


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key without relying on real credentials."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database with the real schema."""
    test_database = tmp_path / "test_auth_integration.db"
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
    """Test client backed by the fixture's temporary database.

    The client is not entered as a context manager because that would run the
    app lifespan and initialize the real development database. The isolated
    schema is created directly through ``Base.metadata`` above.
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
    test_client = TestClient(main.app)
    try:
        yield test_client
    finally:
        test_client.close()
        main.app.dependency_overrides.pop(get_db, None)


def bearer_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_user(
    client: TestClient,
    email: str,
    password: str = TEST_PASSWORD,
) -> dict:
    """Register a user through the real endpoint and return the public record."""
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def login(
    client: TestClient,
    email: str,
    password: str = TEST_PASSWORD,
):
    """Submit the actual OAuth2 password form used by the app."""
    return client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )


def login_token(
    client: TestClient,
    email: str,
    password: str = TEST_PASSWORD,
) -> str:
    """Return the token from a real successful login response."""
    response = login(client, email, password)
    assert response.status_code == 200
    return response.json()["access_token"]


def register_and_login(
    client: TestClient,
    email: str,
    password: str = TEST_PASSWORD,
) -> dict:
    """Register and log in, keeping the genuine token and auth header."""
    user = register_user(client, email, password)
    token = login_token(client, email, password)
    return {
        "user": user,
        "token": token,
        "headers": bearer_header(token),
    }


def assert_no_sensitive_data(response, *sensitive_values: str) -> None:
    """Fail if an error response leaks credentials, hashes, or internals."""
    text = response.text
    assert "hashed_password" not in text
    assert "$argon2id$" not in text
    assert TEST_SECRET not in text
    assert "TASKFLOW_JWT_SECRET" not in text
    assert "traceback" not in text.lower()
    for value in sensitive_values:
        assert value not in text


def assert_authentication_failure(response, *sensitive_values: str) -> None:
    """A protected endpoint must return the dependency's generic 401."""
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": UNAUTHENTICATED_DETAIL}
    assert_no_sensitive_data(response, *sensitive_values)


def assert_login_failure(response, *sensitive_values: str) -> None:
    """Unknown emails and wrong passwords share one non-enumerating 401."""
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": LOGIN_ERROR_DETAIL}
    assert "access_token" not in response.text
    assert_no_sensitive_data(response, *sensitive_values)


@pytest.fixture
def alice(client):
    """Register and log in Alice through the real endpoints."""
    return register_and_login(client, "alice.integration@example.com")


@pytest.fixture
def bob(client):
    """Register and log in Bob through the real endpoints."""
    return register_and_login(client, "bob.integration@example.com")


@pytest.fixture
def alice_task(client, alice):
    """Create a task owned by Alice using Alice's genuine login token."""
    response = client.post(
        "/tasks",
        json={"title": "Alice private task"},
        headers=alice["headers"],
    )
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Complete registration -> login -> authenticated identity workflow
# ---------------------------------------------------------------------------


def test_registration_to_login_to_authenticated_profile_workflow(
    client,
    session_factory,
):
    """Exercise the entire chain using only the real API responses."""
    email = "  Integration.User@Example.COM  "
    normalized_email = "integration.user@example.com"

    registration = client.post(
        "/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )

    assert registration.status_code == 201
    registered = registration.json()
    assert set(registered) == {"id", "email", "created_at"}
    assert registered["email"] == normalized_email
    assert isinstance(registered["id"], int)
    assert registered["id"] > 0
    assert_no_sensitive_data(registration, TEST_PASSWORD)

    # The database must store a one-way Argon2id hash, never the password.
    with session_factory() as session:
        stored = session.scalar(
            select(User).where(User.email == normalized_email)
        )
        assert stored is not None
        assert stored.id == registered["id"]
        assert stored.hashed_password != TEST_PASSWORD
        assert TEST_PASSWORD not in stored.hashed_password
        assert stored.hashed_password.startswith("$argon2id$")
        assert verify_password(TEST_PASSWORD, stored.hashed_password) is True

    login_response = login(client, normalized_email, TEST_PASSWORD)

    assert login_response.status_code == 200
    assert set(login_response.json()) == {"access_token", "token_type"}
    assert login_response.json()["token_type"] == "bearer"
    token = login_response.json()["access_token"]
    assert isinstance(token, str)
    assert token.count(".") == 2
    assert_no_sensitive_data(login_response, TEST_PASSWORD)

    payload = decode_access_token(token, TEST_SECRET)
    assert payload["sub"] == str(registered["id"])
    assert set(payload) == {"sub", "iat", "exp"}

    profile = client.get("/auth/me", headers=bearer_header(token))

    assert profile.status_code == 200
    assert profile.json() == registered
    assert set(profile.json()) == {"id", "email", "created_at"}
    assert_no_sensitive_data(profile, TEST_PASSWORD)


def test_registration_response_does_not_expose_the_password_or_hash(client):
    response = client.post(
        "/auth/register",
        json={"email": "no-leak@example.com", "password": TEST_PASSWORD},
    )

    assert response.status_code == 201
    data = response.json()
    assert "password" not in data
    assert "hashed_password" not in data
    assert_no_sensitive_data(response, TEST_PASSWORD)


def test_registered_hash_is_verifiable_and_not_the_plaintext(client, session_factory):
    user = register_user(client, "hash-check@example.com")

    with session_factory() as session:
        stored = session.get(User, user["id"])
        assert stored is not None
        assert stored.hashed_password.startswith("$argon2id$")
        assert stored.hashed_password != TEST_PASSWORD
        assert verify_password(TEST_PASSWORD, stored.hashed_password) is True

    # Re-registering the same password for another user must produce a new salt.
    other = register_user(client, "hash-check-2@example.com")
    with session_factory() as session:
        first = session.get(User, user["id"])
        second = session.get(User, other["id"])
        assert first.hashed_password != second.hashed_password


# ---------------------------------------------------------------------------
# Authentication failures and non-disclosure
# ---------------------------------------------------------------------------


def test_missing_bearer_token_is_rejected(client):
    assert_authentication_failure(client.get("/auth/me"))


def test_non_bearer_authorization_is_rejected(client, alice):
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Basic {alice['token']}"},
    )

    assert_authentication_failure(response, alice["token"])


@pytest.mark.parametrize(
    "token",
    ["not-a-jwt", "a.b.c", "header.payload.signature"],
    ids=["plain-text", "three-dots", "three-segments"],
)
def test_malformed_token_is_rejected(client, token):
    response = client.get("/auth/me", headers=bearer_header(token))

    assert_authentication_failure(response, token)


def test_tampered_login_token_is_rejected(client, alice):
    header, payload, signature = alice["token"].split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    response = client.get("/auth/me", headers=bearer_header(tampered))

    assert_authentication_failure(response, tampered)


def test_expired_token_is_rejected(client, alice):
    token = create_access_token(
        str(alice["user"]["id"]),
        TEST_SECRET,
        expires_delta=timedelta(minutes=-5),
    )

    response = client.get("/auth/me", headers=bearer_header(token))

    assert_authentication_failure(response, token)


def test_token_signed_with_wrong_secret_is_rejected(client, alice):
    token = create_access_token(str(alice["user"]["id"]), OTHER_TEST_SECRET)

    response = client.get("/auth/me", headers=bearer_header(token))

    assert_authentication_failure(response, token, OTHER_TEST_SECRET)


@pytest.mark.parametrize(
    "invalid_subject",
    ["not-a-user-id", "alice@example.com", "0", "-1", "1.5", "9" * 20],
    ids=[
        "non-numeric",
        "email",
        "zero",
        "negative",
        "decimal",
        "too-many-digits",
    ],
)
def test_token_with_invalid_subject_is_rejected(client, invalid_subject):
    token = create_access_token(invalid_subject, TEST_SECRET)

    response = client.get("/auth/me", headers=bearer_header(token))

    assert_authentication_failure(response, token)


def test_token_for_nonexistent_user_is_rejected(client):
    token = create_access_token("999999", TEST_SECRET)

    response = client.get("/auth/me", headers=bearer_header(token))

    assert_authentication_failure(response, token)


def test_wrong_password_is_rejected_without_disclosure(client, alice):
    wrong_password = "DefinitelyTheWrongPassword123!"
    response = login(client, alice["user"]["email"], wrong_password)

    assert_login_failure(response, wrong_password, TEST_PASSWORD)


def test_unknown_email_is_rejected_without_disclosure(client, alice):
    unknown_email = "nobody@example.com"
    response = login(client, unknown_email, TEST_PASSWORD)

    assert_login_failure(response, unknown_email, TEST_PASSWORD)


def test_unknown_email_and_wrong_password_are_indistinguishable(client, alice):
    unknown = login(client, "nobody@example.com", TEST_PASSWORD)
    wrong_password = login(
        client,
        alice["user"]["email"],
        "DefinitelyTheWrongPassword123!",
    )

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()
    assert (
        unknown.headers["www-authenticate"]
        == wrong_password.headers["www-authenticate"]
        == "Bearer"
    )


def test_authentication_is_required_for_auth_me(client):
    responses = [
        client.get("/auth/me"),
        client.get("/auth/me", headers=bearer_header("malformed.token.value")),
    ]

    for response in responses:
        assert_authentication_failure(response)


# ---------------------------------------------------------------------------
# Authenticated task lifecycle
# ---------------------------------------------------------------------------


def test_authenticated_user_can_create_a_task(
    client,
    alice,
    session_factory,
):
    response = client.post(
        "/tasks",
        json={"title": "Integration task", "completed": False},
        headers=alice["headers"],
    )

    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "Integration task"
    assert created["completed"] is False
    assert set(created) == {
        "id",
        "title",
        "description",
        "status",
        "completed",
        "due_date",
        "created_at",
    }

    with session_factory() as session:
        stored = session.get(Task, created["id"])
        assert stored is not None
        assert stored.user_id == alice["user"]["id"]


def test_authenticated_user_can_list_own_tasks(client, alice):
    first = client.post(
        "/tasks",
        json={"title": "First task"},
        headers=alice["headers"],
    ).json()
    second = client.post(
        "/tasks",
        json={"title": "Second task", "completed": True},
        headers=alice["headers"],
    ).json()

    response = client.get("/tasks", headers=alice["headers"])

    assert response.status_code == 200
    assert {task["id"] for task in response.json()} == {first["id"], second["id"]}
    assert response.headers["X-Total-Count"] == "2"


def test_authenticated_user_can_retrieve_own_task(client, alice, alice_task):
    response = client.get(
        f"/tasks/{alice_task['id']}",
        headers=alice["headers"],
    )

    assert response.status_code == 200
    assert response.json() == alice_task


def test_authenticated_user_can_update_own_task(
    client,
    alice,
    alice_task,
    session_factory,
):
    response = client.patch(
        f"/tasks/{alice_task['id']}",
        json={"title": "Updated title", "completed": True},
        headers=alice["headers"],
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Updated title"
    assert updated["completed"] is True
    assert updated["id"] == alice_task["id"]

    with session_factory() as session:
        stored = session.get(Task, alice_task["id"])
        assert stored is not None
        assert stored.title == "Updated title"
        assert stored.completed is True
        assert stored.user_id == alice["user"]["id"]


def test_authenticated_user_can_delete_own_task(client, alice, alice_task):
    response = client.delete(
        f"/tasks/{alice_task['id']}",
        headers=alice["headers"],
    )

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(
        f"/tasks/{alice_task['id']}",
        headers=alice["headers"],
    ).status_code == 404
    assert client.get("/tasks", headers=alice["headers"]).json() == []


def test_authenticated_task_lifecycle_end_to_end(client, alice):
    created = client.post(
        "/tasks",
        json={"title": "Lifecycle task"},
        headers=alice["headers"],
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    listed = client.get("/tasks", headers=alice["headers"])
    assert listed.status_code == 200
    assert task_id in [task["id"] for task in listed.json()]

    fetched = client.get(f"/tasks/{task_id}", headers=alice["headers"])
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Lifecycle task"

    updated = client.patch(
        f"/tasks/{task_id}",
        json={"completed": True},
        headers=alice["headers"],
    )
    assert updated.status_code == 200
    assert updated.json()["completed"] is True

    deleted = client.delete(f"/tasks/{task_id}", headers=alice["headers"])
    assert deleted.status_code == 204

    assert client.get(
        f"/tasks/{task_id}",
        headers=alice["headers"],
    ).status_code == 404


# ---------------------------------------------------------------------------
# User-to-task ownership isolation
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_user_b_task(client, alice, bob):
    task = client.post(
        "/tasks",
        json={"title": "Bob only"},
        headers=bob["headers"],
    ).json()

    response = client.get(f"/tasks/{task['id']}", headers=alice["headers"])

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR_DETAIL}
    assert task["title"] not in response.text
    assert bob["user"]["email"] not in response.text


def test_user_a_cannot_update_user_b_task(
    client,
    alice,
    bob,
    session_factory,
):
    task = client.post(
        "/tasks",
        json={"title": "Bob only"},
        headers=bob["headers"],
    ).json()

    response = client.patch(
        f"/tasks/{task['id']}",
        json={"title": "Hijacked", "completed": True},
        headers=alice["headers"],
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR_DETAIL}
    assert task["title"] not in response.text
    assert bob["user"]["email"] not in response.text

    with session_factory() as session:
        stored = session.get(Task, task["id"])
        assert stored is not None
        assert stored.title == "Bob only"
        assert stored.completed is False
        assert stored.user_id == bob["user"]["id"]


def test_user_a_cannot_delete_user_b_task(
    client,
    alice,
    bob,
    session_factory,
):
    task = client.post(
        "/tasks",
        json={"title": "Bob only"},
        headers=bob["headers"],
    ).json()

    response = client.delete(f"/tasks/{task['id']}", headers=alice["headers"])

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR_DETAIL}
    assert task["title"] not in response.text
    assert bob["user"]["email"] not in response.text

    with session_factory() as session:
        assert session.get(Task, task["id"]) is not None


def test_each_user_only_lists_their_own_tasks(client, alice, bob, alice_task):
    bob_task = client.post(
        "/tasks",
        json={"title": "Bob private task"},
        headers=bob["headers"],
    ).json()

    alice_list = client.get("/tasks", headers=alice["headers"])
    bob_list = client.get("/tasks", headers=bob["headers"])

    assert alice_list.status_code == bob_list.status_code == 200
    assert [task["id"] for task in alice_list.json()] == [alice_task["id"]]
    assert [task["id"] for task in bob_list.json()] == [bob_task["id"]]
    assert alice_list.headers["X-Total-Count"] == "1"
    assert bob_list.headers["X-Total-Count"] == "1"


def test_task_creation_ignores_a_client_supplied_owner(
    client,
    alice,
    bob,
    session_factory,
):
    response = client.post(
        "/tasks",
        json={"title": "Spoofed owner", "user_id": bob["user"]["id"]},
        headers=alice["headers"],
    )

    assert response.status_code == 201
    created = response.json()

    with session_factory() as session:
        stored = session.get(Task, created["id"])
        assert stored is not None
        assert stored.user_id == alice["user"]["id"]
        assert stored.user_id != bob["user"]["id"]


def test_nonexistent_task_returns_404_for_authenticated_user(client, alice):
    responses = [
        client.get("/tasks/999999", headers=alice["headers"]),
        client.patch(
            "/tasks/999999",
            json={"completed": True},
            headers=alice["headers"],
        ),
        client.delete("/tasks/999999", headers=alice["headers"]),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "Task not found"}


# ---------------------------------------------------------------------------
# Task routes reject missing or invalid authentication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}],
    ids=["no-token", "malformed-token"],
)
def test_task_routes_reject_missing_or_invalid_authentication(
    client,
    headers,
):
    task_id = 1
    requests = [
        ("GET", "/tasks", None),
        ("POST", "/tasks", {"title": "No valid token"}),
        ("GET", f"/tasks/{task_id}", None),
        ("PATCH", f"/tasks/{task_id}", {"completed": True}),
        ("DELETE", f"/tasks/{task_id}", None),
    ]

    for method, path, body in requests:
        response = client.request(method, path, json=body, headers=headers)
        assert_authentication_failure(response)


def test_task_route_rejects_token_for_nonexistent_user(client):
    token = create_access_token("999999", TEST_SECRET)

    response = client.get("/tasks", headers=bearer_header(token))

    assert_authentication_failure(response, token)


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------


def test_temporary_database_is_not_the_development_database(
    session_factory,
    tmp_path,
):
    with session_factory() as session:
        database_path = Path(session.get_bind().url.database).resolve()

    assert database_path != DATABASE_PATH.resolve()
    assert database_path.is_relative_to(tmp_path.resolve())
    assert database_path.exists()


def test_each_client_uses_a_fresh_database(client, alice, session_factory):
    """No data from other tests may bleed into this test's database."""
    with session_factory() as session:
        users = session.scalars(select(User)).all()
        assert [user.id for user in users] == [alice["user"]["id"]]

    assert client.get("/tasks", headers=alice["headers"]).json() == []
