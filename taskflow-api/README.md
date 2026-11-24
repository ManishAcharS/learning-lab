# TaskFlow API

A small task-management REST API built with FastAPI, Pydantic 2, the
SQLAlchemy 2.x ORM, and SQLite. It supports paginated, searchable, filtered
listing, plus creating, retrieving, partially updating, and deleting tasks.
Tasks are persisted in `taskflow.db`, so they survive an application restart.
Every task belongs to exactly one registered user, and all `/tasks` endpoints
require a valid Bearer JWT. Users can only list, read, update, and delete their
own tasks.

## Request lifecycle

1. A client sends an HTTP request to Uvicorn, which runs the FastAPI app.
2. FastAPI matches the request's method and path to a route.
3. For `POST /tasks` and `PATCH /tasks/{task_id}`, Pydantic validates the JSON
   body before the endpoint runs. Invalid input (for example, a missing, empty,
   whitespace-only, wrong-typed, or over-120-character title, or an explicit
   `null` for a non-nullable field) produces a standardized `422` response, and
   the endpoint is not called.
4. FastAPI resolves `get_current_active_user`, which verifies the Bearer JWT and
   loads the user identified by its `sub` claim. Missing or invalid credentials
   produce `401` before the endpoint runs.
5. FastAPI resolves the `get_db` dependency, which opens one SQLAlchemy session
   for the request and promises to close it afterward.
6. The endpoint uses that session to read or modify `Task` ORM objects. Writes
   are committed only after validation succeeds and go through `commit_changes()`;
   created or updated objects are refreshed so database defaults are available.
   An unknown ID raises `HTTPException(404)`. A database commit failure rolls the
   session back and returns a generic `500`, never a success response.
7. FastAPI serializes the ORM object through the `TaskRead` response model and
   sends it with the route's status code (`200`, `201`, or `204`).
8. The `get_db` dependency rolls back on an endpoint exception, then closes the
   session in a `finally` block, even when the endpoint raises.

```text
Client -> Uvicorn -> FastAPI router -> Pydantic validation
       -> JWT dependency (current user) -> get_db dependency (Session)
       -> SQLAlchemy ORM -> SQLite
       <- JSON response <- TaskRead <- session closed in finally
```

## Database layer

| File | Responsibility |
| --- | --- |
| `database.py` | Stable database path, SQLAlchemy engine, `SessionLocal`, declarative `Base`, `get_db`, and `init_db`. |
| `models.py` | The `User` and `Task` ORM models, including the ownership relationship. |
| `main.py` | FastAPI app, request/response schemas, and ownership-aware ORM endpoints. |
| `migrate_task_ownership.py` | Explicit one-off migration for legacy databases; never guesses an owner. |
| `test_main.py` | API tests, each using an isolated temporary SQLite database. |
| `test_ownership.py` | Two-user isolation and 403 authorization tests. |

The database URL is built from `Path(__file__).resolve().parent`, so
`taskflow.db` is always the file next to the application code, regardless of the
terminal's current working directory.

### ORM model

`models.Task` maps to the `tasks` table:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `INTEGER` | Primary key, auto-incrementing (`AUTOINCREMENT`, so deleted IDs are not reused). |
| `title` | `VARCHAR(120)` | Required; a database `CHECK` also enforces 1–120 characters. |
| `description` | `VARCHAR(2000)` | Optional; at most 2,000 characters. |
| `due_date` | `DATE` | Optional; calendar date with no time component. |
| `completed` | `BOOLEAN` | Required; defaults to `false` (`0` in SQLite). |
| `created_at` | `DATETIME` | Required; defaults to the database's `CURRENT_TIMESTAMP`. |
| `user_id` | `INTEGER` | Required foreign key to `users.id`; indexed; cascades on user deletion. |

`status` is a derived API value rather than a stored column: `pending` maps to
`completed = false`, and `completed` maps to `completed = true`. This keeps the
new status vocabulary consistent with the existing persisted boolean.

`models.User` maps to `users` (`id`, unique indexed `email`, `hashed_password`,
and `created_at`). `Task.user` and `User.tasks` are the matching ORM
relationship.

The ORM model is the persistence model: it describes the table and its
constraints. The Pydantic models are transport models: `TaskCreate` and
`TaskUpdate` validate incoming JSON, while `TaskRead` controls the response
shape. `TaskRead` uses `from_attributes=True` to serialize ORM objects and
exposes the same public fields as before: `id`, `title`, `completed`, and the
database-generated `created_at` timestamp. `user_id` is intentionally not part
of the request or response schemas. `TaskCreate` and `TaskUpdate` do not define
`id`, `created_at`, or `user_id`, so clients cannot set those server-owned
fields; values for them are ignored if sent.

### Table creation and existing data

`init_db()` runs during FastAPI startup and calls
`Base.metadata.create_all(bind=engine)`. This only creates missing tables. It
does **not** add columns, change types, or otherwise migrate an existing table.

The existing local `taskflow.db` was inspected before this change. It contains
18 task rows, has no `users` table, and has no `user_id` column. Those legacy
rows have no recorded owner, so they cannot be assigned safely by application
code. This change therefore leaves that file untouched and never guesses an
owner.

Because the project has no migration framework, `migrate_task_ownership.py`
performs the standard SQLite table rebuild explicitly:

```powershell
# Start the API once so init_db() creates the missing users table, register the
# intended owner, then stop the API before running the migration.
python migrate_task_ownership.py --user-email owner@example.com --dry-run
python migrate_task_ownership.py --user-email owner@example.com
```

The script requires exactly one explicit `--user-id` or `--user-email`, refuses
to run without an existing matching user, backs up the database file first,
copies every row with its original ID and `created_at`, adds the non-nullable
foreign key and index, checks foreign keys, and wraps the table swap in one
transaction. It never assigns legacy tasks to an arbitrary user.

Migration limitations: it is a one-off local SQLite tool, not versioned
migration history; it requires the API to be stopped; it rebuilds the `tasks`
table, so the backup (not an automatic rollback command) is the recovery path;
and it should not be used as a substitute for Alembic in a shared or production
database.

### Session lifecycle

1. FastAPI calls `get_db()` while resolving the request.
2. `get_db()` creates a session from `SessionLocal` and yields it to the endpoint.
3. Reads use `db.get(...)` or `db.scalars(select(...))`; writes call
   `db.add(...)`, `db.delete(...)`, and `commit_changes(db)`.
4. `commit_changes()` calls `db.commit()`. On `SQLAlchemyError` it calls
   `db.rollback()`, logs the exception with its traceback on the server, and
   returns a generic `500` response. The exception text is never sent to the
   client.
5. After a successful create or update, `db.refresh(...)` reloads the row so
   database-generated values are current.
6. If an endpoint raises any exception, `get_db()` rolls the session back before
   re-raising it, so the error is not hidden. The `finally` block always calls
   `db.close()`. Closing an uncommitted session also discards pending changes,
   so a rejected or failed request does not persist partial data.

A separate `SQLAlchemyError` exception handler covers unexpected database
errors outside the write helpers (for example, a failed read). It logs the
details server-side and returns the same generic
`{"detail": "Database operation failed"}` body with status `500`.

Using a dependency keeps sessions request-scoped rather than global, guarantees
cleanup, and lets tests replace the real database session with an isolated one.

## Endpoints

All `/tasks` endpoints require a valid Bearer JWT. `/health`, registration, and
`/auth/me` are separate; see the authentication sections below.

| Method | Path | Purpose | Success status |
| --- | --- | --- | --- |
| `GET` | `/health` | Check that the API is running and healthy. | `200` |
| `GET` | `/tasks` | List only the authenticated user's tasks. Supports optional `completed`, `search`, `sort_by`, `sort_order`, `limit`, and `offset` query parameters; defaults to the first 20 owned tasks ordered by ID. | `200` |
| `POST` | `/tasks` | Create a task owned by the authenticated user from a `title` and optional `completed` value. The database assigns the ID. | `201` |
| `GET` | `/tasks/{task_id}` | Retrieve one task only if the authenticated user owns it. | `200` |
| `PATCH` | `/tasks/{task_id}` | Partially update `title` and/or `completed` on an owned task. Omitted fields are left unchanged. | `200` |
| `DELETE` | `/tasks/{task_id}` | Delete an owned task by ID. | `204` |

Ownership is enforced in SQL for listing and by an explicit owner comparison for
single-resource operations. A task that exists but belongs to another user
returns `403` with `{"detail": "Not authorized to access this task"}`. That
message never includes the task contents or the owner's identity. A task ID that
does not exist returns `404` with `{"detail": "Task not found"}`, preserving the
previous behavior. A path value that is not an integer (for example,
`/tasks/not-a-number` or `/tasks/1.5`) fails path validation with `422` before
the endpoint runs.

`POST /tasks` always takes ownership from the verified JWT subject. A
client-supplied `user_id` is ignored. `PATCH /tasks/{task_id}` cannot change
ownership because `TaskUpdate` only accepts task-owned fields.

### Error responses

| Status | Cause | Response body |
| --- | --- | --- |
| `401` | JWT is missing, malformed, expired, tampered with, or references no user | `{"detail": "Could not validate credentials"}` |
| `403` | The task exists but belongs to another user | `{"detail": "Not authorized to access this task"}` |
| `422` | Body, query, or path validation fails | `{"error": "validation_error", "fields": [{"field": "title", "message": "..."}]}` |
| `404` | No task exists with the requested ID | `{"detail": "Task not found"}` |
| `500` | A database operation fails unexpectedly | `{"detail": "Database operation failed"}` |

Every validation failure uses the same body shape, whether the invalid value came
from a body, query parameter, or path segment. One request may report several
fields. Each `message` is a short human-readable explanation; request values,
exception objects, and tracebacks are never included. Nested body locations are
rendered as dotted paths such as `items[0].name`.

A validation failure never creates, updates, or deletes a row. A commit failure
rolls back the pending transaction, so it does not persist a partial write. The
`500` response deliberately contains no SQL, traceback, or database error text;
those details are logged on the server for operators.

### Validation rules

- `title` is required and must be a string between 1 and 120 characters.
- Whitespace-only titles such as `"   "` are rejected with `422`. A title with
  real content may contain or be surrounded by whitespace, which is preserved.
- `description` is optional and may be at most 2,000 characters. Omitting it or
  sending `null` stores no description.
- `status` is optional on create and defaults to `pending`. The only supported
  values are `pending` and `completed`; they map to the existing `completed`
  boolean. Sending both `status` and `completed` is allowed only when they agree.
- `due_date` is optional and uses the `YYYY-MM-DD` date format. A date before the
  server's current date is rejected with `422`; today is accepted.
- `id` and `created_at` are generated by the server. Supplying them in a
  `POST` or `PATCH` body does not set them; the API ignores those extra fields.
- `user_id` is also server-owned: it always comes from the verified JWT. Sending
  it in a `POST` or `PATCH` body is ignored and cannot transfer ownership.
- `completed` must be a boolean. Wrong JSON types (for example, a numeric title,
  an object for `completed`, or a non-boolean string) are rejected with `422`.
- On `PATCH`, fields may be omitted to keep their current values. An empty body
  (`{}`) is a valid no-op that returns the unchanged task with `200`.
- `PATCH` fields may not be explicitly set to JSON `null`. `{"title": null}`,
  `{"status": null}`, and `{"completed": null}` are rejected with `422`, so a
  partial update cannot erase required task data. `description` and `due_date`
  may be cleared with `null`.
- A task ID must be an integer path value. Unknown IDs, including `0` and
  negative integers, return `404`; non-integer values return `422`.

### Duplicate POST requests

`POST /tasks` is **not idempotent**. There is no unique title constraint and no
idempotency-key support, so submitting the same valid request twice creates two
separate records with different auto-assigned IDs. Both requests return `201`.
This is the current, documented behavior rather than a guarantee of exactly-once
creation.

If a client retries a POST after a timeout, it may create a duplicate when the
first request had already committed. Idempotent retries would require an
additional client-supplied key, a uniqueness constraint, and stored results;
that infrastructure is intentionally not part of this API yet.

### Filtering, searching, sorting, and pagination

`GET /tasks` accepts optional query parameters. Invalid values are rejected
with `422 Unprocessable Entity` before the endpoint runs.

| Parameter | Allowed values | Default | Behavior |
| --- | --- | --- | --- |
| `completed` | `true` or `false` | omitted | When omitted, every task is considered. When set, only tasks whose `completed` value matches are returned. |
| `search` | 1–100 characters | omitted | Case-insensitive substring match on `title`. `%` and `_` are treated as literal characters, not SQL wildcards. |
| `sort_by` | `id`, `title`, `completed` | `id` | Selects the column used for ordering. Only these fixed column names are accepted. |
| `sort_order` | `asc`, `desc` | `asc` | Selects ascending or descending order. Ties are broken by ascending ID. |
| `limit` | integer 1–100 | `20` | Maximum number of tasks returned in this page. |
| `offset` | integer 0 or greater | `0` | Number of matching tasks to skip before returning the page. |

Filtering, searching, sorting, counting, and pagination are performed by
SQLAlchemy in SQL, not by loading every row and slicing it in Python. The total
is counted with the same filters as the page query. A filter that matches no
tasks returns `200` with an empty JSON array (`[]`), not `404`.

Every successful list response includes these headers:

| Header | Meaning |
| --- | --- |
| `X-Total-Count` | Number of tasks matching the filters, before `limit`/`offset`. |
| `X-Limit` | Effective page size (the requested value or the default). |
| `X-Offset` | Effective offset (the requested value or the default). |

The response body remains a plain JSON array of tasks; pagination metadata is
only in the headers.

```bash
# Only completed tasks (first 20 by ID)
curl "http://127.0.0.1:8000/tasks?completed=true"

# Case-insensitive title search
curl "http://127.0.0.1:8000/tasks?search=fastapi"

# All tasks, newest first
curl "http://127.0.0.1:8000/tasks?sort_by=id&sort_order=desc"

# Incomplete tasks, sorted by title A-Z
curl "http://127.0.0.1:8000/tasks?completed=false&sort_by=title&sort_order=asc"

# Third page of 10, with total/limit/offset metadata in response headers
curl "http://127.0.0.1:8000/tasks?limit=10&offset=20"

# Invalid: returns 422 instead of sorting by an arbitrary column
curl "http://127.0.0.1:8000/tasks?sort_by=created_at"
```

Omitting all parameters returns the first 20 tasks ordered by ascending ID.
An offset past the last matching row returns `200`, an empty array, and headers
whose `X-Total-Count` still reports the full filtered total.

### Example requests

Every `/tasks` example below needs an access token. Register a user, obtain a
JWT signed with `TASKFLOW_JWT_SECRET` for that user's ID, and send it as
`Authorization: Bearer <token>`. The examples omit that header for brevity.

```bash
# List the authenticated user's tasks
curl http://127.0.0.1:8000/tasks -H "Authorization: Bearer $TASKFLOW_TOKEN"

# Create a task -> 201 with id, title, description, status,
# completed, due_date, and created_at
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Write documentation", "status": "pending",
       "due_date": "2026-12-01"}'

# Create a completed task
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Ship release", "status": "completed"}'

# Partial update -> 200; omitted fields keep their current values
curl -X PATCH http://127.0.0.1:8000/tasks/1 \
  -H "Content-Type: application/json" \
  -d '{"completed": true}'

# Empty partial update -> 200 with the unchanged task
curl -X PATCH http://127.0.0.1:8000/tasks/1 \
  -H "Content-Type: application/json" \
  -d '{}'

# Delete -> 204 with an empty body
curl -X DELETE http://127.0.0.1:8000/tasks/1

# Missing title -> 422; no task is created
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{}'

# Whitespace-only title -> 422; no task is created
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "   "}'

# Unknown task -> 404 {"detail": "Task not found"}
curl http://127.0.0.1:8000/tasks/999

# Non-integer task ID -> 422 before the endpoint runs
curl http://127.0.0.1:8000/tasks/not-a-number

# Sending the same POST twice creates two tasks with different IDs
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Duplicate request"}'
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Duplicate request"}'
```

Interactive API documentation is available at `/docs` (Swagger UI) and
`/redoc` while the server is running.

## Project structure

```text
taskflow-api/
|-- main.py                     # FastAPI app, schemas, ownership-aware CRUD
|-- database.py                 # Engine, Base, SessionLocal, get_db, init_db
|-- models.py                   # User/Task ORM models and relationship
|-- deps.py                     # JWT authentication dependency
|-- security.py                 # JWT and password hashing utilities
|-- migrate_task_ownership.py   # Explicit legacy-data ownership migration
|-- test_main.py                # API tests with isolated temporary databases
|-- test_ownership.py           # Two-user ownership/isolation tests
|-- test_auth.py                # Registration tests
|-- test_auth_deps.py           # Authentication dependency tests
|-- test_security.py            # JWT/password utility tests
|-- database_practice.py        # Standalone sqlite3 practice script (unchanged)
|-- requirements.txt            # Pinned runtime dependencies
|-- requirements-dev.txt        # Runtime plus test dependencies
|-- .gitignore                  # Local databases, caches, and secret files
|-- taskflow.db                 # Local development database (not tracked)
`-- README.md
```

## Setup and running the tests

From the `taskflow-api` directory, create and activate a virtual environment,
install the dependencies, and run pytest:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

`requirements.txt` pins the runtime dependencies; `requirements-dev.txt`
includes them and adds the test dependencies. The project requires Python 3.10
or newer.

On macOS or Linux, activate the environment with
`source .venv/bin/activate` instead.

The suite currently contains 161 tests. Each test creates a fresh SQLite file
under pytest's `tmp_path`, creates the schema from the ORM metadata, and installs
a `get_db` dependency override. Task API tests seed three known tasks owned by a
temporary test user and authenticate with that user's signed JWT. The
test-client helper always removes the override, and each request-scoped session
is closed in a `finally` block. The temporary database is discarded afterward,
so tests never delete or modify the real `taskflow.db`, and one test cannot leak
state into another. The test override also rolls back on exceptions, matching
the production dependency.
Focused isolation tests verify the temporary database path, override cleanup,
and that the real development database file is unchanged.

`test_ownership.py` registers two independent users through the real
registration endpoint and authenticates each with a genuine JWT. It verifies
separate task creation, owner-only listing, reading, updating, and deleting,
403 responses for another user's existing task, unchanged data after failed
updates/deletes, ignored client-supplied `user_id` on create and patch, 404 for
nonexistent tasks, and 401 for unauthenticated task requests.

`test_task_validation.py` covers the strict task rules and the global 422
contract: missing, empty, whitespace-only, and over-length titles; descriptions
over 2,000 characters; unsupported statuses; past due dates; acceptance of
today's due date; successful creation with every field; multiple simultaneous
field errors; and consistent bodies for query and path errors. It also asserts
that responses never include the submitted sensitive value, exception names,
Pydantic wording, tracebacks, or input objects. All due dates are relative to
the current date and each test uses an isolated temporary database.

The tests cover the health check, task listing and retrieval, creation and
validation (including missing, empty, whitespace-only, wrong-typed, and
over-length titles), invalid path parameters, partial updates, empty PATCH
bodies, rejection of explicit `null` values, invalid PATCH values, duplicate
POST requests, unique ID generation after deletion (including deletion of the
highest ID), deletion behavior, filtering by both boolean values,
case-insensitive title search, combined search and completion filters, empty
filter results, invalid boolean/search query values, whitelisted sorting fields
and directions (including rejection of unsupported or injection-style values),
stable ID tie-breaking, database-generated timestamps and `completed` defaults,
rejection of client-supplied `id`/`created_at`, and direct database inserts that
violate the title `CHECK` constraint. Pagination tests cover defaults, custom
limit/offset, page slicing, filtered totals, invalid bounds, out-of-range
offsets, response headers, and public-field serialization. Database commit and
read failures are simulated with monkeypatched sessions to verify rollback,
generic `500` responses, and the absence of leaked internals.

## Running the API locally

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

On startup, missing tables are created in `taskflow.db`. Then open
<http://127.0.0.1:8000/docs> or call the endpoints at
<http://127.0.0.1:8000>.

## Current limitations

- **Authentication required; no roles or admin features.** Task routes are
  restricted to the authenticated owner. Existing tasks cannot be assigned an
  owner automatically.
- **No migration framework.** `create_all()` only creates missing tables;
  changing an existing schema requires the separate, explicit migration script
  or a tool such as Alembic.
- **SQLite only.** The project is intended for local learning and small
  workloads, not for high-concurrency or multi-server deployment.
- **Simple substring search.** `search` uses SQL `LIKE` on `title`; there is no
  full-text index, tokenization, ranking, or multi-column search.
- **Offset pagination only.** Large offsets still require SQLite to scan the
  skipped rows. Cursor pagination would be needed for very large datasets.
- **Single-resource updates only.** There is no bulk create/update/delete.
- **POST is not idempotent.** Repeated or retried requests can create duplicate
  tasks. There are no idempotency keys or unique-title constraints.
- **Generic database errors.** Database failures return a fixed `500` detail and
  are logged server-side. There is no retry policy or structured error code.
- **Commit/refresh edge case.** If a commit succeeds but the subsequent refresh
  or response serialization fails, the write may already be persisted even
  though the client sees an error. A POST retry in that situation can duplicate
  the record.
