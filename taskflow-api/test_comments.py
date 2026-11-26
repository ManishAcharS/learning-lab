"""Tests for the task comments resource.

Every test uses an isolated temporary SQLite database. SQLite foreign-key
enforcement is enabled explicitly so cascade behavior is exercised by the
database rather than only by the ORM.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from deps import JWT_SECRET_ENV_VAR
from models import Comment, Task
from security import create_access_token

TEST_SECRET = (
    "test-only-comments-secret-never-use-in-production-"
    "with-enough-length-for-hs256-tests"
)
TEST_PASSWORD = "SuperSecretPassword123!"
OWNERSHIP_ERROR = "Not authorized to access this task"
NOT_FOUND_ERROR = {"detail": "Task not found"}


@pytest.fixture(autouse=True)
def configure_jwt_secret(monkeypatch):
    """Provide a test signing key for authenticated comment tests."""
    monkeypatch.setenv(JWT_SECRET_ENV_VAR, TEST_SECRET)


@pytest.fixture
def test_engine(tmp_path):
    """Create an isolated SQLite database that enforces foreign keys."""
    test_database = tmp_path / "test_comments.db"
    engine = create_engine(
        f"sqlite:///{test_database.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(test_engine):
    return sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )


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


def create_task(client, user, title="A task") -> dict:
    response = client.post(
        "/tasks",
        json={"title": title},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def owned_tasks(client, users):
    alice, bob = users
    return {
        "alice": create_task(client, alice, title="Alice private task"),
        "bob": create_task(client, bob, title="Bob private task"),
    }


def create_comment(client, user, task_id, body="A useful comment") -> dict:
    response = client.post(
        f"/tasks/{task_id}/comments",
        json={"body": body},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()


def comment_count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Comment)) or 0


def test_authorized_user_can_create_a_comment(client, users, owned_tasks):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]

    response = client.post(
        f"/tasks/{task_id}/comments",
        json={"body": "Looks good to me"},
        headers=auth_headers(alice),
    )

    assert response.status_code == 201
    created = response.json()
    assert created["body"] == "Looks good to me"
    assert set(created) == {
        "id",
        "task_id",
        "author_id",
        "body",
        "created_at",
    }


def test_comment_uses_url_task_and_authenticated_author(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, bob = users
    alice_task_id = owned_tasks["alice"]["id"]

    response = client.post(
        f"/tasks/{alice_task_id}/comments",
        json={
            "body": "Server-owned fields",
            "task_id": owned_tasks["bob"]["id"],
            "author_id": bob["id"],
        },
        headers=auth_headers(alice),
    )

    assert response.status_code == 201
    created = response.json()
    assert created["task_id"] == alice_task_id
    assert created["author_id"] == alice["id"]
    assert created["author_id"] != bob["id"]

    with session_factory() as session:
        stored = session.get(Comment, created["id"])
        assert stored is not None
        assert stored.task_id == alice_task_id
        assert stored.author_id == alice["id"]


@pytest.mark.parametrize(
    "body",
    ["", "   ", "\n\t  \r\n"],
    ids=["empty", "spaces", "mixed-whitespace"],
)
def test_empty_or_whitespace_only_bodies_are_rejected(
    client,
    users,
    owned_tasks,
    body,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]

    response = client.post(
        f"/tasks/{task_id}/comments",
        json={"body": body},
        headers=auth_headers(alice),
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert any(field["field"] == "body" for field in payload["fields"])


def test_excessively_long_body_is_rejected(client, users, owned_tasks):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]

    response = client.post(
        f"/tasks/{task_id}/comments",
        json={"body": "x" * 2001},
        headers=auth_headers(alice),
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert any(field["field"] == "body" for field in payload["fields"])


def test_authorized_user_can_list_a_tasks_comments(client, users, owned_tasks):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]
    first = create_comment(client, alice, task_id, body="First")
    second = create_comment(client, alice, task_id, body="Second")

    response = client.get(
        f"/tasks/{task_id}/comments",
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    assert {comment["id"] for comment in response.json()} == {
        first["id"],
        second["id"],
    }
    assert response.headers["X-Total-Count"] == "2"
    assert response.headers["X-Limit"] == "20"
    assert response.headers["X-Offset"] == "0"


def test_comments_are_returned_newest_first(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]
    oldest = create_comment(client, alice, task_id, body="Oldest")
    middle = create_comment(client, alice, task_id, body="Middle")
    newest = create_comment(client, alice, task_id, body="Newest")

    with session_factory() as session:
        session.get(Comment, oldest["id"]).created_at = datetime(
            2026, 1, 1, 12, 0, tzinfo=timezone.utc
        )
        session.get(Comment, middle["id"]).created_at = datetime(
            2026, 1, 2, 12, 0, tzinfo=timezone.utc
        )
        session.get(Comment, newest["id"]).created_at = datetime(
            2026, 1, 3, 12, 0, tzinfo=timezone.utc
        )
        session.commit()

    response = client.get(
        f"/tasks/{task_id}/comments",
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    assert [comment["id"] for comment in response.json()] == [
        newest["id"],
        middle["id"],
        oldest["id"],
    ]


def test_equal_created_at_values_use_id_descending_as_tiebreaker(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]
    first = create_comment(client, alice, task_id, body="First")
    second = create_comment(client, alice, task_id, body="Second")

    same_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    with session_factory() as session:
        session.get(Comment, first["id"]).created_at = same_time
        session.get(Comment, second["id"]).created_at = same_time
        session.commit()

    response = client.get(
        f"/tasks/{task_id}/comments",
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    assert [comment["id"] for comment in response.json()] == [
        second["id"],
        first["id"],
    ]


def test_limit_and_offset_paginate_comments(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]
    created = [
        create_comment(client, alice, task_id, body=f"Comment {index}")
        for index in range(5)
    ]

    same_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    with session_factory() as session:
        for comment in created:
            session.get(Comment, comment["id"]).created_at = same_time
        session.commit()

    response = client.get(
        f"/tasks/{task_id}/comments",
        params={"limit": 2, "offset": 1},
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    expected_ids = [comment["id"] for comment in reversed(created)][1:3]
    assert [comment["id"] for comment in response.json()] == expected_ids
    assert response.headers["X-Total-Count"] == "5"
    assert response.headers["X-Limit"] == "2"
    assert response.headers["X-Offset"] == "1"


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"limit": -1}, "limit"),
        ({"limit": "not-an-integer"}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": "not-an-integer"}, "offset"),
    ],
    ids=[
        "limit-zero",
        "limit-too-large",
        "limit-negative",
        "limit-not-integer",
        "offset-negative",
        "offset-not-integer",
    ],
)
def test_invalid_pagination_values_are_rejected(
    client,
    users,
    owned_tasks,
    params,
    field,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]

    response = client.get(
        f"/tasks/{task_id}/comments",
        params=params,
        headers=auth_headers(alice),
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert any(error["field"] == field for error in payload["fields"])


def test_user_without_task_access_cannot_create_comments(
    client,
    users,
    owned_tasks,
    session_factory,
):
    _, bob = users
    alice_task_id = owned_tasks["alice"]["id"]

    response = client.post(
        f"/tasks/{alice_task_id}/comments",
        json={"body": "Unauthorized comment"},
        headers=auth_headers(bob),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR}
    assert "Unauthorized comment" not in response.text
    assert owned_tasks["alice"]["title"] not in response.text
    assert comment_count(session_factory) == 0


def test_user_without_task_access_cannot_list_comments(
    client,
    users,
    owned_tasks,
):
    alice, bob = users
    alice_task_id = owned_tasks["alice"]["id"]
    secret = create_comment(client, alice, alice_task_id, body="Private remark")

    response = client.get(
        f"/tasks/{alice_task_id}/comments",
        headers=auth_headers(bob),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": OWNERSHIP_ERROR}
    assert secret["body"] not in response.text
    assert owned_tasks["alice"]["title"] not in response.text


def test_nonexistent_task_returns_404_for_comments(client, users):
    alice, _ = users
    headers = auth_headers(alice)

    create_response = client.post(
        "/tasks/999999/comments",
        json={"body": "No parent"},
        headers=headers,
    )
    list_response = client.get("/tasks/999999/comments", headers=headers)

    assert create_response.status_code == 404
    assert create_response.json() == NOT_FOUND_ERROR
    assert list_response.status_code == 404
    assert list_response.json() == NOT_FOUND_ERROR


def test_soft_deleted_task_cannot_receive_or_list_comments(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]
    existing = create_comment(client, alice, task_id, body="Before deletion")

    deleted = client.delete(
        f"/tasks/{task_id}",
        headers=auth_headers(alice),
    )
    assert deleted.status_code == 204

    create_response = client.post(
        f"/tasks/{task_id}/comments",
        json={"body": "After deletion"},
        headers=auth_headers(alice),
    )
    list_response = client.get(
        f"/tasks/{task_id}/comments",
        headers=auth_headers(alice),
    )

    assert create_response.status_code == 404
    assert create_response.json() == NOT_FOUND_ERROR
    assert list_response.status_code == 404
    assert list_response.json() == NOT_FOUND_ERROR
    assert comment_count(session_factory) == 1
    assert existing["body"] not in list_response.text


def test_physical_task_delete_cascades_to_comments_in_the_database(
    client,
    users,
    owned_tasks,
    session_factory,
):
    alice, _ = users
    task_id = owned_tasks["alice"]["id"]
    create_comment(client, alice, task_id, body="Will be cascaded")
    create_comment(client, alice, task_id, body="Also cascaded")
    assert comment_count(session_factory) == 2

    with session_factory() as session:
        foreign_keys_enabled = session.execute(
            text("PRAGMA foreign_keys")
        ).scalar_one()
        assert foreign_keys_enabled == 1

        # Bypass the ORM so only the database-level ON DELETE CASCADE can
        # remove the comments.
        session.execute(
            text("DELETE FROM tasks WHERE id = :task_id"),
            {"task_id": task_id},
        )
        session.commit()

    assert comment_count(session_factory) == 0


def test_existing_task_and_auth_behavior_remains_intact(client, users):
    alice, _ = users
    task = create_task(client, alice, title="Still works")
    headers = auth_headers(alice)

    unauthenticated = [
        client.get(f"/tasks/{task['id']}/comments"),
        client.post(
            f"/tasks/{task['id']}/comments",
            json={"body": "No token"},
        ),
    ]
    for response in unauthenticated:
        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}

    listed = client.get("/tasks", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [task["id"]]
    assert client.get(
        f"/tasks/{task['id']}",
        headers=headers,
    ).status_code == 200
