# Changelog

All notable changes to TaskFlow API are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/).

Baseline: the project had no Git tag for v0.1.0. The v0.1 baseline is the
release-preparation commit `817aa3f7` ("chore: prepare TaskFlow for release"),
which contained unauthenticated task CRUD backed by SQLite.

## [0.2.0] - 2026-11-28

### Added

- **Authentication and profiles**
  - `POST /auth/register` creates an account with a unique, normalized email and
    an Argon2id password hash.
  - `POST /auth/login` implements the OAuth2 password flow and issues an HS256
    Bearer JWT.
  - `GET /auth/me` returns the authenticated user's safe public profile.
- **Per-user ownership and tenant isolation** for every task route, including
  `403` for another user's task and `404` for missing or soft-deleted tasks.
- **Task querying** on `GET /tasks`: filtering by completion state,
  case-insensitive title search, allow-listed sorting, and offset pagination
  with `X-Total-Count`, `X-Limit`, and `X-Offset` response headers.
- **Strict task schemas** for create and partial update, including title,
  description, due-date, status/completed consistency, and a standardized `422`
  validation response.
- **Soft deletion and restore** through `DELETE /tasks/{task_id}` and
  `POST /tasks/{task_id}/restore`, backed by a `deleted_at` column and Alembic
  revisions.
- **Task comments** through `POST /tasks/{task_id}/comments` and
  `GET /tasks/{task_id}/comments`, with ownership checks and paginated,
  newest-first listing.
- **Database-aware health check** at `GET /health`, returning `200` when
  `SELECT 1` succeeds and a safe `503` body when the database is unreachable.
- **Alembic migrations** for the baseline schema, task soft deletion, and the
  comments table.
- **Docker deployment assets**: a multi-stage `python:3.12-slim` image running as
  a non-root user, a Compose stack with PostgreSQL readiness checks, and
  environment-based configuration documented in `.env.example`.
- **OpenAPI documentation** for every implemented operation, with summaries,
  descriptions, authentication requirements, response codes, and request/response
  examples. The generated schema is saved at `docs/openapi.json`.

### Changed

- The application reads `DATABASE_URL` from the environment while retaining the
  existing local SQLite file as the default.
- `GET /health` now reports database readiness and includes a `database` field.
- Task boolean defaults use the portable SQL literal `false`, allowing the same
  schema to run on SQLite and PostgreSQL.
- The API metadata now reports version `0.2.0`.
- README endpoint and deployment documentation now reflect the implemented API.

### Security

- Passwords are hashed with Argon2id and never returned by the API.
- JWTs require an explicit `TASKFLOW_JWT_SECRET`; there is no fallback signing
  key.
- Login is limited to five requests per minute per client IP.
- Ownership failures do not reveal another user's task contents or identity.
- Health and database error responses do not expose connection strings,
  credentials, stack traces, or internal exception details.

### Development

- Expanded the test suite to cover authentication, ownership, validation, soft
  deletion, comments, rate limiting, health checks, and database helpers.
- Added `pytest-cov` and saved the current coverage summary at
  `docs/coverage-2026-11-28.txt`.

## [0.1.0] - Baseline (untagged)

- Task CRUD over SQLite using FastAPI, Pydantic 2, and SQLAlchemy 2.x.
- Request-scoped database sessions and generic database error handling.
- Basic health endpoint and automated CRUD tests.
