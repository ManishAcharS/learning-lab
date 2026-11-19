"""Ownership and user-level data-isolation tests for task CRUD.

Every test runs against its own temporary SQLite database. Two real registered
users are created through the API, and requests are authenticated with each
user's genuine signed JWT.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import Task
from security import create_access_token

# Test-only signing key. Production code reads TASKFLOW_JWT_SECRET.
TEST_SECRET = (
    "test-only-ownership-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_PASSWORD = "SuperSecretPassword123!"
OWNERSHIP_ERROR = "Not authorized to access this task"


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key for authenticated ownership tests."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database with the real schema."""
    test_database = tmp_path / "test_ownership.db"
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


def register_user(client, email: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


def auth_headers(user: dict) -> dict[str, str]:
    token = create_access_token(str(user["id"]), TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def users(client):
    """Register two independent users through the real registration endpoint."""
    return (
        register_user(client, "alice@example.com"),
        register_user(client, "bob@example.com"),
    )


@pytest.fixture
def owned_tasks(client, users):
    """Create one task for each user."""
    alice, bob = users
    alice_task = client.post(
        "/tasks",
        json={"title": "Alice private task"},
        headers=auth_headers(alice),
    ).json()
    bob_task = client.post(
        "/tasks",
        json={"title": "Bob private task"},
        headers=auth_headers(bob),
    ).json()
    return {"alice": alice_task, "bob": bob_task}


def test_user_a_can_create_a_task(client, users, session_factory):
    alice, _ = users

    response = client.post(
        "/tasks",
        json={"title": "Alice task"},
        headers=auth_headers(alice),
    )

    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "Alice task"
    assert set(created) == {"id", "title", "completed", "created_at"}

    with session_factory() as session:
        stored = session.get(Task, created["id"])
        assert stored is not None
        assert stored.user_id == alice["id"]


def test_user_b_can_create_a_task(client, users, session_factory):
    _, bob = users

    response = client.post(
        "/tasks",
        json={"title": "Bob task"},
        headers=auth_headers(bob),
    )

    assert response.status_code == 201
    created = response.json()

    with session_factory() as session:
        stored = session.get(Task, created["id"])
        assert stored is not None
        assert stored.user_id == bob["id"]


def test_user_a_sees_only_user_a_tasks(client, users, owned_tasks):
    alice, _ = users

    response = client.get("/tasks", headers=auth_headers(alice))

    assert response.status_code == 200
    assert [task["id"] for task in response.json()] == [
        owned_tasks["alice"]["id"]
    ]
    assert response.headers["X-Total-Count"] == "1"


def test_user_b_sees_only_user_b_tasks(client, users, owned_tasks):
    _, bob = users

    response = client.get("/tasks", headers=auth_headers(bob))

    assert response.status_code == 200
    assert [task["id"] for task in response.json()] == [
        owned_tasks["bob"]["id"]
    ]
    assert response.headers["X-Total-Count"] == "1"


def test_user_a_can_read_their_own_task(client, users, owned_tasks):
    alice, _ = users

    response = client.get(
        f"/tasks/{owned_tasks['alice']['id']}",
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    assert response.json() == owned_tasks["alice"]


def test_user_b_can_read_their_own_task(client, users, owned_tasks):
    _, bob = users

    response = client.get(
        f"/tasks/{owned_tasks['bob']['id']}",
        headers=auth_headers(bob),
    )

    assert response.status_code == 200
    assert response.json() == owned_tasks["bob"]


def test_user_a_receives_403_reading_user_b_task(client, users, owned_tasks):
    alice, bob = users

    response = client.get(
        f"/tasks/{owned_tasks['bob']['id']}",
        headers=auth_headers(alice),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR}
    assert owned_tasks["bob"]["title"] not in response.text
    assert bob["email"] not in response.text


def test_user_a_receives_403_updating_user_b_task(client, users, owned_tasks):
    alice, bob = users

    response = client.patch(
        f"/tasks/{owned_tasks['bob']['id']}",
        json={"title": "Hijacked"},
        headers=auth_headers(alice),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR}
    assert owned_tasks["bob"]["title"] not in response.text
    assert bob["email"] not in response.text


def test_user_a_receives_403_deleting_user_b_task(client, users, owned_tasks):
    alice, bob = users

    response = client.delete(
        f"/tasks/{owned_tasks['bob']['id']}",
        headers=auth_headers(alice),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR}
    assert owned_tasks["bob"]["title"] not in response.text
    assert bob["email"] not in response.text


def test_user_b_task_is_unchanged_after_user_a_failed_update(
    client,
    users,
    owned_tasks,
):
    alice, bob = users

    client.patch(
        f"/tasks/{owned_tasks['bob']['id']}",
        json={"title": "Hijacked", "completed": True},
        headers=auth_headers(alice),
    )

    response = client.get(
        f"/tasks/{owned_tasks['bob']['id']}",
        headers=auth_headers(bob),
    )

    assert response.status_code == 200
    assert response.json() == owned_tasks["bob"]


def test_user_b_task_still_exists_after_user_a_failed_delete(
    client,
    users,
    owned_tasks,
):
    alice, bob = users

    client.delete(
        f"/tasks/{owned_tasks['bob']['id']}",
        headers=auth_headers(alice),
    )

    response = client.get(
        f"/tasks/{owned_tasks['bob']['id']}",
        headers=auth_headers(bob),
    )

    assert response.status_code == 200
    assert response.json() == owned_tasks["bob"]


def test_create_ignores_client_supplied_user_id(
    client,
    users,
    session_factory,
):
    alice, bob = users

    response = client.post(
        "/tasks",
        json={"title": "Spoofed owner", "user_id": bob["id"]},
        headers=auth_headers(alice),
    )

    assert response.status_code == 201
    created = response.json()

    with session_factory() as session:
        stored = session.get(Task, created["id"])
        assert stored is not None
        assert stored.user_id == alice["id"]
        assert stored.user_id != bob["id"]

    assert created["id"] in [
        task["id"]
        for task in client.get("/tasks", headers=auth_headers(alice)).json()
    ]
    assert created["id"] not in [
        task["id"]
        for task in client.get("/tasks", headers=auth_headers(bob)).json()
    ]


def test_patch_cannot_change_task_ownership(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, bob = users
    bob_task_id = owned_tasks["bob"]["id"]

    response = client.patch(
        f"/tasks/{bob_task_id}",
        json={"title": "Legitimate rename", "user_id": alice["id"]},
        headers=auth_headers(bob),
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Legitimate rename"

    with session_factory() as session:
        stored = session.get(Task, bob_task_id)
        assert stored is not None
        assert stored.user_id == bob["id"]
        assert stored.user_id != alice["id"]

    # Alice still cannot reach the task, even after the rejected ownership swap.
    assert client.get(
        f"/tasks/{bob_task_id}",
        headers=auth_headers(alice),
    ).status_code == 403


def test_nonexistent_task_returns_404_for_authenticated_user(client, users):
    alice, _ = users
    headers = auth_headers(alice)

    read_response = client.get("/tasks/999999", headers=headers)
    update_response = client.patch(
        "/tasks/999999",
        json={"completed": True},
        headers=headers,
    )
    delete_response = client.delete("/tasks/999999", headers=headers)

    for response in (read_response, update_response, delete_response):
        assert response.status_code == 404
        assert response.json() == {"detail": "Task not found"}


def test_unauthenticated_requests_remain_rejected(client, owned_tasks):
    task_id = owned_tasks["alice"]["id"]

    responses = [
        client.get("/tasks"),
        client.post("/tasks", json={"title": "No token"}),
        client.get(f"/tasks/{task_id}"),
        client.patch(f"/tasks/{task_id}", json={"completed": True}),
        client.delete(f"/tasks/{task_id}"),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {"detail": "Could not validate credentials"}
