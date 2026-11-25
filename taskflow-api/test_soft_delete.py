"""Tests for task soft deletion, active filtering, and restoration.

Each test runs against its own temporary SQLite database. Users are registered
through the real API and authenticated with genuine signed JWTs.
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

TEST_SECRET = (
    "test-only-soft-delete-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_PASSWORD = "SuperSecretPassword123!"
OWNERSHIP_ERROR = "Not authorized to access this task"
NOT_FOUND_ERROR = {"detail": "Task not found"}


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key for authenticated task tests."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def session_factory(tmp_path):
    """Create an isolated temporary SQLite database with the real schema."""
    test_database = tmp_path / "test_soft_delete.db"
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


def create_task(client, user, title="A task", **fields) -> dict:
    response = client.post(
        "/tasks",
        json={"title": title, **fields},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()


def stored_task(session_factory, task_id: int) -> Task | None:
    with session_factory() as session:
        return session.get(Task, task_id)


def test_delete_sets_deleted_at_without_removing_the_row(
    client,
    users,
    session_factory,
):
    alice, _ = users
    task = create_task(client, alice, title="Keep the row")

    assert Task.__table__.c.deleted_at.type.timezone is True
    assert stored_task(session_factory, task["id"]).deleted_at is None

    response = client.delete(
        f"/tasks/{task['id']}",
        headers=auth_headers(alice),
    )

    assert response.status_code == 204
    stored = stored_task(session_factory, task["id"])
    assert stored is not None
    assert stored.id == task["id"]
    assert stored.title == "Keep the row"
    assert stored.deleted_at is not None


def test_deleted_task_disappears_from_list_and_count(client, users):
    alice, _ = users
    kept = create_task(client, alice, title="Still active")
    removed = create_task(client, alice, title="Goes away")

    assert client.delete(
        f"/tasks/{removed['id']}",
        headers=auth_headers(alice),
    ).status_code == 204

    response = client.get("/tasks", headers=auth_headers(alice))

    assert response.status_code == 200
    assert [task["id"] for task in response.json()] == [kept["id"]]
    assert response.headers["X-Total-Count"] == "1"


def test_get_deleted_task_returns_404(client, users):
    alice, _ = users
    task = create_task(client, alice, title="Hidden after delete")

    client.delete(f"/tasks/{task['id']}", headers=auth_headers(alice))

    response = client.get(
        f"/tasks/{task['id']}",
        headers=auth_headers(alice),
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND_ERROR


def test_restore_makes_the_task_visible_again(client, users, session_factory):
    alice, _ = users
    task = create_task(client, alice, title="Restore me")
    client.delete(f"/tasks/{task['id']}", headers=auth_headers(alice))

    response = client.post(
        f"/tasks/{task['id']}/restore",
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    assert response.json()["id"] == task["id"]
    assert stored_task(session_factory, task["id"]).deleted_at is None
    assert client.get(
        f"/tasks/{task['id']}",
        headers=auth_headers(alice),
    ).status_code == 200
    listed = client.get("/tasks", headers=auth_headers(alice))
    assert [item["id"] for item in listed.json()] == [task["id"]]
    assert listed.headers["X-Total-Count"] == "1"

    # Restoring an already-active task is idempotent.
    again = client.post(
        f"/tasks/{task['id']}/restore",
        headers=auth_headers(alice),
    )
    assert again.status_code == 200
    assert again.json()["id"] == task["id"]


def test_another_user_cannot_restore_the_task(
    client,
    users,
    session_factory,
):
    alice, bob = users
    task = create_task(client, alice, title="Alice only")
    client.delete(f"/tasks/{task['id']}", headers=auth_headers(alice))

    response = client.post(
        f"/tasks/{task['id']}/restore",
        headers=auth_headers(bob),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR}
    assert task["title"] not in response.text
    assert stored_task(session_factory, task["id"]).deleted_at is not None

    # The owner can still restore it afterward.
    assert client.post(
        f"/tasks/{task['id']}/restore",
        headers=auth_headers(alice),
    ).status_code == 200


def test_restoring_a_nonexistent_task_returns_404(client, users):
    alice, _ = users

    response = client.post(
        "/tasks/999999/restore",
        headers=auth_headers(alice),
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND_ERROR


def test_repeated_delete_keeps_the_original_timestamp(
    client,
    users,
    session_factory,
):
    alice, _ = users
    task = create_task(client, alice, title="Delete twice")

    first = client.delete(
        f"/tasks/{task['id']}",
        headers=auth_headers(alice),
    )
    assert first.status_code == 204
    first_deleted_at = stored_task(session_factory, task["id"]).deleted_at
    assert first_deleted_at is not None

    second = client.delete(
        f"/tasks/{task['id']}",
        headers=auth_headers(alice),
    )

    assert second.status_code == 404
    assert second.json() == NOT_FOUND_ERROR
    assert stored_task(
        session_factory, task["id"]
    ).deleted_at == first_deleted_at
    assert client.get("/tasks", headers=auth_headers(alice)).json() == []


def test_list_filters_sorting_and_pagination_ignore_deleted_tasks(client, users):
    alice, _ = users
    zebra = create_task(client, alice, title="zebra", completed=True)
    removed = create_task(client, alice, title="apple", completed=False)
    mango = create_task(client, alice, title="mango", completed=True)
    banana = create_task(client, alice, title="banana", completed=False)

    assert client.delete(
        f"/tasks/{removed['id']}",
        headers=auth_headers(alice),
    ).status_code == 204

    completed = client.get(
        "/tasks?completed=true&sort_by=id&sort_order=desc",
        headers=auth_headers(alice),
    )
    assert completed.status_code == 200
    assert [task["id"] for task in completed.json()] == [mango["id"], zebra["id"]]
    assert completed.headers["X-Total-Count"] == "2"

    searched = client.get(
        "/tasks?search=mango",
        headers=auth_headers(alice),
    )
    assert [task["id"] for task in searched.json()] == [mango["id"]]
    assert searched.headers["X-Total-Count"] == "1"

    by_title = client.get(
        "/tasks?sort_by=title&sort_order=asc",
        headers=auth_headers(alice),
    )
    assert [task["title"] for task in by_title.json()] == [
        "banana",
        "mango",
        "zebra",
    ]

    page = client.get(
        "/tasks?sort_by=id&sort_order=asc&limit=2&offset=1",
        headers=auth_headers(alice),
    )
    assert [task["id"] for task in page.json()] == [mango["id"], banana["id"]]
    assert page.headers["X-Total-Count"] == "3"
    assert page.headers["X-Limit"] == "2"
    assert page.headers["X-Offset"] == "1"
