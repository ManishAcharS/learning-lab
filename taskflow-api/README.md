# TaskFlow API

A small task-management REST API built with FastAPI and Pydantic. It supports
listing, creating, retrieving, partially updating, and deleting tasks. Tasks are
kept in memory, so this project is intended for learning and local experiments
rather than production use.

## Request lifecycle

1. A client sends an HTTP request to Uvicorn, which runs the FastAPI app.
2. FastAPI matches the request's method and path to a route.
3. For `POST /tasks` and `PATCH /tasks/{task_id}`, Pydantic validates the JSON
   body before the endpoint runs. Invalid input (for example, a missing or empty
   title, or an explicit `null`) produces an automatic `422 Unprocessable
   Entity` response, and the endpoint is not called.
4. The endpoint reads or mutates the module-level `tasks` list in `main.py`.
   Task lookups use `_find_task`; an unknown ID raises `HTTPException(404)`.
5. FastAPI serializes the returned Python dictionary to JSON and sends it with
   the route's status code (`200`, `201`, or `204`).

In short:

```text
Client -> Uvicorn -> FastAPI router -> Pydantic validation -> endpoint
       <- JSON response <- FastAPI serialization <- in-memory tasks
```

## Endpoints

| Method | Path | Purpose | Success status |
| --- | --- | --- | --- |
| `GET` | `/health` | Check that the API is running and healthy. | `200` |
| `GET` | `/tasks` | List every task. | `200` |
| `POST` | `/tasks` | Create a task from a `title` and optional `completed` value. The server assigns the ID. | `201` |
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

## Current limitations

- **No persistence.** Tasks live in the module-level `tasks` list and reset to
  the two seed tasks whenever the process restarts.
- **No database.** There is no storage layer, migrations, or transaction
  handling.
- **No authentication or authorization.** Every caller can read and modify all
  tasks.
- **No concurrency control.** Concurrent requests mutate a shared list without
  locking, so behavior under parallel writes is not guaranteed.
- **Basic ID generation.** New IDs are `max(existing IDs) + 1`. Deleting the
  task with the highest ID can cause that ID to be reused later.
- **No pagination, filtering, sorting, or search.** `GET /tasks` always returns
  the full list.
- **Single-resource updates only.** There is no bulk create/update/delete.
- **Minimal error handling.** Besides FastAPI's validation responses and the
  `404` for unknown tasks, there is no custom error envelope or logging.

## Project structure

```text
taskflow-api/
|-- main.py        # FastAPI app, models, and in-memory task store
|-- test_main.py   # API tests using FastAPI's TestClient and pytest
`-- README.md
```

## Running the tests

From the `taskflow-api` directory, create and activate a virtual environment,
install the dependencies, and run pytest:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi uvicorn pytest httpx
python -m pytest -v
```

On macOS or Linux, activate the environment with
`source .venv/bin/activate` instead.

Each test starts from a known copy of the seed tasks and restores the original
list afterward, so tests do not depend on execution order. The suite covers the
health check, task listing and retrieval, creation and validation, partial
updates, rejection of explicit `null` values, unique ID generation after a
deletion, and deletion behavior.

## Running the API locally

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

Then open <http://127.0.0.1:8000/docs> or call the endpoints at
<http://127.0.0.1:8000>.
