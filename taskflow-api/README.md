# TaskFlow API

A small task-management REST API built with FastAPI, Pydantic 2, the
SQLAlchemy 2.x ORM, and SQLite. It supports listing, creating, retrieving,
partially updating, and deleting tasks. Tasks are persisted in
`taskflow.db`, so they survive an application restart.

## Request lifecycle

1. A client sends an HTTP request to Uvicorn, which runs the FastAPI app.
2. FastAPI matches the request's method and path to a route.
3. For `POST /tasks` and `PATCH /tasks/{task_id}`, Pydantic validates the JSON
   body before the endpoint runs. Invalid input (for example, a missing or empty
   title, or an explicit `null`) produces an automatic `422 Unprocessable
   Entity` response, and the endpoint is not called.
4. FastAPI resolves the `get_db` dependency, which opens one SQLAlchemy session
   for the request and promises to close it afterward.
5. The endpoint uses that session to read or modify `Task` ORM objects. Writes
   are committed only after validation succeeds; created or updated objects are
   refreshed so database defaults are available. An unknown ID raises
   `HTTPException(404)`.
6. FastAPI serializes the ORM object through the `TaskRead` response model and
   sends it with the route's status code (`200`, `201`, or `204`).
7. The `get_db` dependency closes the session in a `finally` block, even when
   the endpoint raises an exception.

```text
Client -> Uvicorn -> FastAPI router -> Pydantic validation
       -> get_db dependency (Session) -> SQLAlchemy ORM -> SQLite
       <- JSON response <- TaskRead <- session closed in finally
```

## Database layer

| File | Responsibility |
| --- | --- |
| `database.py` | Stable database path, SQLAlchemy engine, `SessionLocal`, declarative `Base`, `get_db`, and `init_db`. |
| `models.py` | The `Task` ORM model mapped to the `tasks` table. |
| `main.py` | FastAPI app, request/response schemas, and ORM-based endpoints. |
| `test_main.py` | API tests, each using an isolated temporary SQLite database. |

The database URL is built from `Path(__file__).resolve().parent`, so
`taskflow.db` is always the file next to the application code, regardless of the
terminal's current working directory.

### ORM model

`models.Task` maps to the `tasks` table:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `INTEGER` | Primary key, auto-incrementing (`AUTOINCREMENT`, so deleted IDs are not reused). |
| `title` | `VARCHAR(100)` | Required; a database `CHECK` also enforces 1–100 characters. |
| `completed` | `BOOLEAN` | Required; defaults to `false` (`0` in SQLite). |
| `created_at` | `DATETIME` | Required; defaults to the database's `CURRENT_TIMESTAMP`. |

The ORM model is the persistence model: it describes the table and its
constraints. The Pydantic models are transport models: `TaskCreate` and
`TaskUpdate` validate incoming JSON, while `TaskRead` controls the response
shape. `TaskRead` uses `from_attributes=True` to serialize ORM objects, and it
intentionally exposes only `id`, `title`, and `completed`; `created_at` is stored
but not part of the existing API response.

### Table creation and existing data

`init_db()` runs during FastAPI startup and calls
`Base.metadata.create_all(bind=engine)`. This only creates missing tables. It
does **not** add columns, change types, or otherwise migrate an existing table.

The existing `taskflow.db` was inspected before these changes. Its `tasks` table
already has `id`, `title`, `completed`, and `created_at` with compatible
constraints and defaults, and it contains three practice rows. No migration was
needed, and the file and its data were left intact. If the schema must change in
the future, back up `taskflow.db` and apply a deliberate migration (for example,
with Alembic or reviewed SQL); do not delete the database to force a new schema.

### Session lifecycle

1. FastAPI calls `get_db()` while resolving the request.
2. `get_db()` creates a session from `SessionLocal` and yields it to the endpoint.
3. Reads use `db.get(...)` or `db.scalars(select(...))`; writes call
   `db.add(...)`, `db.delete(...)`, and `db.commit()`.
4. After a successful create or update, `db.refresh(...)` reloads the row so
   database-generated values are current.
5. The `finally` block always calls `db.close()`. Closing an uncommitted session
   rolls back its pending transaction, so a rejected request does not persist
   partial changes.

Using a dependency keeps sessions request-scoped rather than global, guarantees
cleanup, and lets tests replace the real database session with an isolated one.

## Endpoints

| Method | Path | Purpose | Success status |
| --- | --- | --- | --- |
| `GET` | `/health` | Check that the API is running and healthy. | `200` |
| `GET` | `/tasks` | List tasks from SQLite. Supports optional `completed`, `sort_by`, and `sort_order` query parameters; defaults to all tasks ordered by ID. | `200` |
| `POST` | `/tasks` | Create a task from a `title` and optional `completed` value. The database assigns the ID. | `201` |
| `GET` | `/tasks/{task_id}` | Retrieve one task by ID. | `200` |
| `PATCH` | `/tasks/{task_id}` | Partially update `title` and/or `completed`. Omitted fields are left unchanged. | `200` |
| `DELETE` | `/tasks/{task_id}` | Delete a task by ID. | `204` |

Requests for a task ID that does not exist return `404` with
`{"detail": "Task not found"}`.

### Validation rules

- `title` must be a string between 1 and 100 characters.
- `completed` must be a boolean.
- On `PATCH`, fields may be omitted to keep their current values, but they may
  not be explicitly set to JSON `null`. `{"title": null}` and
  `{"completed": null}` are rejected with `422`, so a partial update cannot
  erase required task data.

### Filtering and sorting tasks

`GET /tasks` accepts three optional query parameters. Invalid values are
rejected with `422 Unprocessable Entity` before the endpoint runs.

| Parameter | Allowed values | Default | Behavior |
| --- | --- | --- | --- |
| `completed` | `true` or `false` | omitted | When omitted, every task is returned (the original behavior). When set, only tasks whose `completed` value matches are returned. |
| `sort_by` | `id`, `title`, `completed` | `id` | Selects the column used for ordering. Only these fixed column names are accepted. |
| `sort_order` | `asc`, `desc` | `asc` | Selects ascending or descending order. Ties are broken by ascending ID. |

Filtering and sorting are performed by SQLAlchemy in the SQL query, not in
Python. A filter that matches no tasks returns `200` with an empty JSON array
(`[]`), not `404`.

```bash
# Only completed tasks (default order: ID ascending)
curl "http://127.0.0.1:8000/tasks?completed=true"

# Only incomplete tasks
curl "http://127.0.0.1:8000/tasks?completed=false"

# All tasks, newest first
curl "http://127.0.0.1:8000/tasks?sort_by=id&sort_order=desc"

# Incomplete tasks, sorted by title A-Z
curl "http://127.0.0.1:8000/tasks?completed=false&sort_by=title&sort_order=asc"

# Invalid: returns 422 instead of sorting by an arbitrary column
curl "http://127.0.0.1:8000/tasks?sort_by=created_at"
```

Omitting all three parameters produces exactly the same response as before
this feature was added: every task, ordered by ascending ID.

### Example requests

```bash
curl http://127.0.0.1:8000/tasks

curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Write documentation", "completed": false}'

curl -X PATCH http://127.0.0.1:8000/tasks/1 \
  -H "Content-Type: application/json" \
  -d '{"completed": true}'

curl -X DELETE http://127.0.0.1:8000/tasks/1
```

Interactive API documentation is available at `/docs` (Swagger UI) and
`/redoc` while the server is running.

## Project structure

```text
taskflow-api/
|-- main.py              # FastAPI app, Pydantic schemas, CRUD endpoints
|-- database.py          # Engine, Base, SessionLocal, get_db, init_db
|-- models.py            # Task SQLAlchemy ORM model
|-- test_main.py         # API tests with isolated temporary databases
|-- database_practice.py # Standalone sqlite3 practice script (unchanged)
|-- taskflow.db          # Development SQLite database
`-- README.md
```

## Setup and running the tests

From the `taskflow-api` directory, create and activate a virtual environment,
install the dependencies, and run pytest:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi uvicorn pytest httpx "SQLAlchemy>=2.0"
python -m pytest -v
```

On macOS or Linux, activate the environment with
`source .venv/bin/activate` instead.

The suite currently contains 29 tests. Each test creates a fresh SQLite file
under pytest's `tmp_path`, creates the schema from the ORM metadata, seeds two
known tasks, and installs a `get_db` dependency override. The temporary database
is discarded afterward, so tests never delete or modify the real
`taskflow.db`, and one test cannot leak state into another.

The tests cover the health check, task listing and retrieval, creation and
validation, partial updates, rejection of explicit `null` values, unique ID
generation after deletion (including deletion of the highest ID), deletion
behavior, filtering by both boolean values, empty filter results, invalid
boolean query values, and whitelisted sorting fields and directions (including
rejection of unsupported or injection-style values).

## Running the API locally

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

On startup, missing tables are created in `taskflow.db`. Then open
<http://127.0.0.1:8000/docs> or call the endpoints at
<http://127.0.0.1:8000>.

## Current limitations

- **No authentication or authorization.** Every caller can read and modify all
  tasks.
- **No migration framework.** `create_all()` only creates missing tables;
  changing an existing schema requires a separate migration.
- **SQLite only.** The project is intended for local learning and small
  workloads, not for high-concurrency or multi-server deployment.
- **No pagination or search.** `GET /tasks` supports filtering and sorting but
  always returns every matching task, without limit/offset or text search.
- **Single-resource updates only.** There is no bulk create/update/delete.
- **Minimal error handling.** Besides FastAPI's validation responses and the
  `404` for unknown tasks, there is no custom error envelope or logging.
