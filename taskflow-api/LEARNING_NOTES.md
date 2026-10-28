# TaskFlow API — Learning Notes

## SQLAlchemy ORM

- **ORM:** Maps Python classes to database tables.
- **Model:** Defines the structure of a database record.
- **Engine:** Connects SQLAlchemy to the database.
- **Session:** Manages database operations and transactions.
- **Dependency injection:** FastAPI's `get_db()` provides a database session to a route and ensures it is closed afterward.
- **Test isolation:** Using a temporary SQLite database for tests prevents test data from changing the real database.

## What I verified

- CRUD operations work with SQLite persistence.
- Tasks survive a server restart.
- Automated tests use an isolated test database.
- Test result: 13 passed, 1 warning.

## Next step

Learn database migrations and improve API response schemas.
