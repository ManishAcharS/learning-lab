"""Tests for the TaskFlow FastAPI application."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

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
        except Exception:
            # Mirror production get_db: roll back, then let the error propagate.
            session.rollback()
            raise
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


def test_get_tasks_without_filter_returns_all_tasks(client):
    """Omitting the filter should preserve the original list behavior."""
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == SEED_TASKS


def test_get_tasks_filters_by_completed_true(client):
    """completed=true should return only completed tasks."""
    created = client.post(
        "/tasks",
        json={"title": "Write tests", "completed": True},
    ).json()

    response = client.get("/tasks", params={"completed": "true"})

    assert response.status_code == 200
    assert response.json() == [created]


def test_get_tasks_filters_by_completed_false(client):
    """completed=false should return only incomplete tasks."""
    response = client.get("/tasks", params={"completed": "false"})

    assert response.status_code == 200
    assert response.json() == SEED_TASKS


def test_get_tasks_filter_returns_empty_list_when_no_task_matches(client):
    """A filter that matches nothing should return [], not 404."""
    response = client.get("/tasks", params={"completed": "true"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "value",
    ["not-a-boolean", "", "2"],
    ids=["text", "empty", "integer"],
)
def test_get_tasks_rejects_invalid_completed_filter(client, value):
    """A value that is not a boolean should fail query validation."""
    response = client.get("/tasks", params={"completed": value})

    assert response.status_code == 422
    assert any(
        error["loc"] == ["query", "completed"]
        for error in response.json()["detail"]
    )


@pytest.mark.parametrize(
    ("sort_by", "sort_order", "expected_ids"),
    [
        ("id", "asc", [1, 2, 3]),
        ("id", "desc", [3, 2, 1]),
        ("title", "asc", [2, 1, 3]),
        ("title", "desc", [3, 1, 2]),
        ("completed", "asc", [1, 2, 3]),
        ("completed", "desc", [3, 1, 2]),
    ],
)
def test_get_tasks_supports_validated_sorting(
    client, sort_by, sort_order, expected_ids
):
    """Allowed sort fields and directions should order results in SQL."""
    # Add one completed task with a title that sorts after both seeds.
    client.post("/tasks", json={"title": "Zebra task", "completed": True})

    response = client.get(
        "/tasks",
        params={"sort_by": sort_by, "sort_order": sort_order},
    )

    assert response.status_code == 200
    assert [task["id"] for task in response.json()] == expected_ids


@pytest.mark.parametrize(
    "params",
    [
        {"sort_by": "created_at"},
        {"sort_by": "id; DROP TABLE tasks"},
        {"sort_order": "sideways"},
    ],
    ids=["unsupported-field", "sql-injection", "invalid-direction"],
)
def test_get_tasks_rejects_invalid_sort_parameters(client, params):
    """Only whitelisted sort fields and directions should be accepted."""
    response = client.get("/tasks", params=params)

    assert response.status_code == 422
    field = next(iter(params))
    assert any(
        error["loc"] == ["query", field]
        for error in response.json()["detail"]
    )


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


def test_create_task_rejects_whitespace_only_title(client):
    """A title containing only whitespace must not create a record."""
    response = client.post("/tasks", json={"title": " \t\n "})

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "title"]
        for error in response.json()["detail"]
    )
    assert client.get("/tasks").json() == SEED_TASKS


@pytest.mark.parametrize(
    "payload",
    [
        {"title": 123},
        {"title": ["not", "a", "string"]},
        {"title": "Valid title", "completed": "definitely-not-a-boolean"},
        {"title": "Valid title", "completed": {"unexpected": True}},
    ],
    ids=["numeric-title", "list-title", "invalid-completed-string", "object-completed"],
)
def test_create_task_rejects_invalid_field_types(client, payload):
    """Fields with the wrong JSON types should fail without inserting rows."""
    response = client.post("/tasks", json=payload)

    assert response.status_code == 422
    assert client.get("/tasks").json() == SEED_TASKS


def test_create_task_rejects_excessively_long_title(client):
    """A title over the 100-character limit should be rejected atomically."""
    response = client.post("/tasks", json={"title": "x" * 101})

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "title"]
        for error in response.json()["detail"]
    )
    assert client.get("/tasks").json() == SEED_TASKS


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


@pytest.mark.parametrize(
    "task_id",
    ["abc", "1.5", "1e2"],
    ids=["text", "float", "scientific-notation"],
)
def test_get_task_rejects_invalid_path_parameter(client, task_id):
    """Non-integer path values should fail path validation with 422."""
    response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 422
    assert any(
        error["loc"] == ["path", "task_id"]
        for error in response.json()["detail"]
    )


@pytest.mark.parametrize("task_id", [0, -1], ids=["zero", "negative"])
def test_get_task_returns_404_for_unassigned_ids(client, task_id):
    """Zero and negative integers are valid ints but never assigned IDs."""
    response = client.get(f"/tasks/{task_id}")

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


def test_patch_task_returns_404_for_unknown_id(client):
    """Patching a missing task should fail without touching existing rows."""
    before = client.get("/tasks").json()

    response = client.patch("/tasks/999", json={"completed": True})

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
    assert client.get("/tasks").json() == before


def test_patch_task_with_empty_body_is_a_noop(client):
    """An empty partial update is valid and leaves the task unchanged."""
    before = client.get("/tasks/1").json()

    response = client.patch("/tasks/1", json={})

    assert response.status_code == 200
    assert response.json() == before
    assert client.get("/tasks/1").json() == before
    assert client.get("/tasks").json() == SEED_TASKS


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 101},
        {"title": 123},
        {"completed": "definitely-not-a-boolean"},
    ],
    ids=["empty-title", "blank-title", "long-title", "numeric-title", "bad-completed"],
)
def test_patch_task_rejects_invalid_values_without_changing_data(client, payload):
    """Invalid patch values should return 422 and leave the row untouched."""
    before = client.get("/tasks/1").json()
    field = next(iter(payload))

    response = client.patch("/tasks/1", json=payload)

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", field]
        for error in response.json()["detail"]
    )
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


def test_delete_unknown_task_returns_404_without_changes(client):
    """Deleting an ID that was never assigned should not alter other tasks."""
    before = client.get("/tasks").json()

    response = client.delete("/tasks/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
    assert client.get("/tasks").json() == before


def test_duplicate_post_creates_two_separate_tasks(client):
    """POST is not idempotent: repeating a request creates another task."""
    payload = {"title": "Duplicate request", "completed": False}

    first = client.post("/tasks", json=payload)
    second = client.post("/tasks", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["title"] == second.json()["title"] == payload["title"]

    listed = client.get("/tasks").json()
    assert len(listed) == len(SEED_TASKS) + 2
    assert [task["id"] for task in listed].count(first.json()["id"]) == 1
    assert [task["id"] for task in listed].count(second.json()["id"]) == 1


def _track_rollbacks(monkeypatch):
    """Record Session.rollback calls while preserving the real behavior."""
    original_rollback = Session.rollback
    rollbacks = []

    def tracking_rollback(session):
        rollbacks.append(session)
        return original_rollback(session)

    monkeypatch.setattr(Session, "rollback", tracking_rollback)
    return rollbacks


def _force_commit_failure(monkeypatch):
    """Make the next commits fail and expose the rollback call log."""
    rollbacks = _track_rollbacks(monkeypatch)
    message = "simulated database failure"

    def failing_commit(session):
        raise SQLAlchemyError(message)

    monkeypatch.setattr(Session, "commit", failing_commit)
    return rollbacks, message


def test_create_commit_failure_returns_generic_500_and_rolls_back(
    client, monkeypatch
):
    """A failed insert commit must roll back and never report success."""
    rollbacks, message = _force_commit_failure(monkeypatch)

    response = client.post("/tasks", json={"title": "Must not persist"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Database operation failed"}
    assert message not in response.text
    assert rollbacks
    assert client.get("/tasks").json() == SEED_TASKS


def test_patch_commit_failure_returns_generic_500_and_rolls_back(
    client, monkeypatch
):
    """A failed update commit must leave the original row unchanged."""
    before = client.get("/tasks/1").json()
    rollbacks, message = _force_commit_failure(monkeypatch)

    response = client.patch("/tasks/1", json={"title": "Must not persist"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Database operation failed"}
    assert message not in response.text
    assert rollbacks
    assert client.get("/tasks/1").json() == before


def test_delete_commit_failure_returns_generic_500_and_rolls_back(
    client, monkeypatch
):
    """A failed delete commit must leave the task retrievable."""
    before = client.get("/tasks/2").json()
    rollbacks, message = _force_commit_failure(monkeypatch)

    response = client.delete("/tasks/2")

    assert response.status_code == 500
    assert response.json() == {"detail": "Database operation failed"}
    assert message not in response.text
    assert rollbacks
    assert client.get("/tasks/2").json() == before


def test_read_failure_returns_generic_500_without_internals(client, monkeypatch):
    """An unexpected read error must be logged, rolled back, and hidden."""
    rollbacks = _track_rollbacks(monkeypatch)
    message = "simulated read failure"

    def failing_get(session, *args, **kwargs):
        raise SQLAlchemyError(message)

    monkeypatch.setattr(Session, "get", failing_get)

    response = client.get("/tasks/1")

    assert response.status_code == 500
    assert response.json() == {"detail": "Database operation failed"}
    assert message not in response.text
    assert rollbacks
