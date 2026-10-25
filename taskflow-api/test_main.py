"""Tests for the TaskFlow FastAPI application."""

import copy

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

SEED_TASKS = [
    {"id": 1, "title": "Learn FastAPI", "completed": False},
    {"id": 2, "title": "Build my first API", "completed": False},
]


@pytest.fixture(autouse=True)
def isolated_task_store():
    """Give each test the seed data, then restore the original in-memory list.

    ``main.tasks`` is a module-level list, so every test shares it. Copying the
    list before and after each test keeps tests independent of execution order
    and prevents one test's changes from leaking into another.
    """
    original = copy.deepcopy(main.tasks)
    main.tasks[:] = copy.deepcopy(SEED_TASKS)
    yield
    main.tasks[:] = original


def test_health_returns_200():
    """The health endpoint should be reachable and report a healthy status."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "message": "TaskFlow api is running",
    }


def test_get_tasks_returns_expected_tasks():
    """The task list should contain exactly the seeded tasks."""
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == SEED_TASKS


def test_create_task_returns_201():
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
def test_create_task_rejects_invalid_title(payload):
    """A missing or empty title should fail validation with 422."""
    response = client.post("/tasks", json=payload)

    assert response.status_code == 422
    assert len(client.get("/tasks").json()) == len(SEED_TASKS)


def test_get_task_returns_existing_task():
    """Fetching a seeded task ID should return that task."""
    response = client.get("/tasks/2")

    assert response.status_code == 200
    assert response.json() == SEED_TASKS[1]


def test_get_task_returns_404_for_unknown_id():
    """Fetching an ID that does not exist should return 404."""
    response = client.get("/tasks/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}


def test_patch_task_updates_only_supplied_fields():
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
def test_patch_task_rejects_explicit_null(field):
    """An explicit null must fail validation instead of clearing a field."""
    before = client.get("/tasks/1").json()

    response = client.patch("/tasks/1", json={field: None})

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", field] for error in errors)
    # The rejected request must not change the task or any other task.
    assert client.get("/tasks/1").json() == before
    assert client.get("/tasks").json() == SEED_TASKS


def test_create_task_uses_unique_id_after_deletion():
    """Deleting a task must not cause the next created task to reuse an ID."""
    assert client.delete("/tasks/1").status_code == 204

    response = client.post("/tasks", json={"title": "Replacement task"})

    assert response.status_code == 201
    created = response.json()
    assert created["id"] == 3

    task_ids = [task["id"] for task in client.get("/tasks").json()]
    assert len(task_ids) == len(set(task_ids))


def test_delete_task_returns_204_then_404():
    """Deleting a task should return 204; deleting it again should return 404."""
    response = client.delete("/tasks/1")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tasks/1").status_code == 404
    assert [task["id"] for task in client.get("/tasks").json()] == [2]

    response = client.delete("/tasks/1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
