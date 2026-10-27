"""Tests for the TaskFlow FastAPI application."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base, get_db
from models import Task

SEED_TASKS = [
    {"id": 1, "title": "Learn FastAPI", "completed": False},
    {"id": 2, "title": "Build my first API", "completed": False},
]


@pytest.fixture
def client(tmp_path):
    """Run each test against its own temporary SQLite database.

    The production ``taskflow.db`` is never opened. A dependency override
    points the API at a fresh database file under pytest's ``tmp_path``, and
    the file is discarded when the test finishes.
    """
    test_database = tmp_path / "test_taskflow.db"
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

    with TestingSessionLocal() as session:
        session.add_all(
            Task(
                id=task["id"],
                title=task["title"],
                completed=task["completed"],
            )
            for task in SEED_TASKS
        )
        session.commit()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_get_db
    # Entering the TestClient as a context manager would run the app lifespan,
    # which initializes the real development database. These tests create their
    # own schema, so they use the client without triggering that startup hook.
    test_client = TestClient(main.app)
    try:
        yield test_client
    finally:
        test_client.close()
        main.app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()


def test_health_returns_200(client):
    """The health endpoint should be reachable and report a healthy status."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "message": "TaskFlow api is running",
    }


def test_get_tasks_returns_expected_tasks(client):
    """The task list should contain exactly the seeded tasks."""
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == SEED_TASKS


def test_create_task_returns_201(client):
    """Posting a valid task should create it with a server-assigned ID."""
    response = client.post(
        "/tasks",
        json={"title": "Write tests", "completed": True},
    )

    assert response.status_code == 201
    created = response.json()
    assert created == {"id": 3, "title": "Write tests", "completed": True}

    # The new task must also be visible when listing tasks.
    listed_tasks = client.get("/tasks").json()
    assert len(listed_tasks) == len(SEED_TASKS) + 1
    assert listed_tasks[-1] == created


@pytest.mark.parametrize(
    "payload",
    [{}, {"title": ""}],
    ids=["missing-title", "empty-title"],
)
def test_create_task_rejects_invalid_title(client, payload):
    """A missing or empty title should fail validation with 422."""
    response = client.post("/tasks", json=payload)

    assert response.status_code == 422
    assert len(client.get("/tasks").json()) == len(SEED_TASKS)


def test_get_task_returns_existing_task(client):
    """Fetching a seeded task ID should return that task."""
    response = client.get("/tasks/2")

    assert response.status_code == 200
    assert response.json() == SEED_TASKS[1]


def test_get_task_returns_404_for_unknown_id(client):
    """Fetching an ID that does not exist should return 404."""
    response = client.get("/tasks/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}


def test_patch_task_updates_only_supplied_fields(client):
    """A partial update should change only the fields present in the body."""
    # Change only completed; title must stay the same.
    response = client.patch("/tasks/1", json={"completed": True})

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "title": "Learn FastAPI",
        "completed": True,
    }

    # Change only title; the previously updated completed value must persist.
    response = client.patch("/tasks/1", json={"title": "Learn FastAPI in depth"})

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "title": "Learn FastAPI in depth",
        "completed": True,
    }

    # Changes are persisted, and unrelated tasks are untouched.
    assert client.get("/tasks/1").json() == {
        "id": 1,
        "title": "Learn FastAPI in depth",
        "completed": True,
    }
    assert client.get("/tasks/2").json() == SEED_TASKS[1]


@pytest.mark.parametrize("field", ["title", "completed"])
def test_patch_task_rejects_explicit_null(client, field):
    """An explicit null must fail validation instead of clearing a field."""
    before = client.get("/tasks/1").json()

    response = client.patch("/tasks/1", json={field: None})

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", field] for error in errors)
    # The rejected request must not change the task or any other task.
    assert client.get("/tasks/1").json() == before
    assert client.get("/tasks").json() == SEED_TASKS


def test_create_task_uses_unique_id_after_deletion(client):
    """Deleting a task must not cause the next created task to reuse an ID."""
    assert client.delete("/tasks/1").status_code == 204

    response = client.post("/tasks", json={"title": "Replacement task"})

    assert response.status_code == 201
    created = response.json()
    assert created["id"] == 3

    task_ids = [task["id"] for task in client.get("/tasks").json()]
    assert len(task_ids) == len(set(task_ids))


def test_create_task_does_not_reuse_highest_id(client):
    """AUTOINCREMENT prevents reuse even after deleting the highest ID."""
    assert client.delete("/tasks/2").status_code == 204

    response = client.post("/tasks", json={"title": "Another task"})

    assert response.status_code == 201
    assert response.json()["id"] == 3


def test_delete_task_returns_204_then_404(client):
    """Deleting a task should return 204; deleting it again should return 404."""
    response = client.delete("/tasks/1")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tasks/1").status_code == 404
    assert [task["id"] for task in client.get("/tasks").json()] == [2]

    response = client.delete("/tasks/1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
