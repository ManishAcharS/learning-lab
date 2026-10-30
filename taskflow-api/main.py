import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Task


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables when the application starts. Existing tables are
    # left untouched; create_all does not perform schema migrations.
    init_db()
    yield


app = FastAPI(title="Taskflow API", lifespan=lifespan)

DbSession = Annotated[Session, Depends(get_db)]

logger = logging.getLogger(__name__)
DATABASE_ERROR_DETAIL = "Database operation failed"


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(request: Request, exc: SQLAlchemyError):
    """Log database failures and return a generic response, never internals."""
    logger.error(
        "Unhandled database error",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": DATABASE_ERROR_DETAIL},
    )


def commit_changes(db: Session) -> None:
    """Commit pending changes, rolling back and hiding internals on failure."""
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database commit failed")
        raise HTTPException(
            status_code=500,
            detail=DATABASE_ERROR_DETAIL,
        ) from None


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "message": "TaskFlow api is running"
    }


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    completed: bool = False

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty or whitespace-only")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    completed: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        # Omitted fields never reach this validator, so partial updates still
        # leave them unchanged. An explicit JSON null, however, is rejected.
        if value is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        if not value.strip():
            raise ValueError("title must not be empty or whitespace-only")
        return value

    @field_validator("completed")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        return value


class TaskRead(BaseModel):
    """Response shape for a task; created_at stays internal to the database."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    completed: bool


SortField = Literal["id", "title", "completed"]
SortOrder = Literal["asc", "desc"]

# Explicit whitelist: clients choose a name, never a SQL expression.
SORT_COLUMNS = {
    "id": Task.id,
    "title": Task.title,
    "completed": Task.completed,
}


@app.get("/tasks", response_model=list[TaskRead])
def get_tasks(
    db: DbSession,
    completed: bool | None = None,
    sort_by: SortField = "id",
    sort_order: SortOrder = "asc",
):
    statement = select(Task)

    # Filter in SQL; False must still apply, so compare explicitly to None.
    if completed is not None:
        statement = statement.where(Task.completed == completed)

    sort_column = SORT_COLUMNS[sort_by]
    if sort_order == "asc":
        statement = statement.order_by(sort_column.asc())
    else:
        statement = statement.order_by(sort_column.desc())

    # Ties get a stable, predictable order without changing the requested sort.
    if sort_by != "id":
        statement = statement.order_by(Task.id.asc())

    return db.scalars(statement).all()


@app.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(task: TaskCreate, db: DbSession):
    new_task = Task(title=task.title, completed=task.completed)
    db.add(new_task)
    commit_changes(db)
    db.refresh(new_task)
    return new_task


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: DbSession):
    task = db.get(Task, task_id)
    if task is not None:
        return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )


@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, update: TaskUpdate, db: DbSession):
    task = db.get(Task, task_id)
    if task is not None:
        # Keep omitted fields unchanged during a partial update.
        changes = update.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(task, field, value)

        commit_changes(db)
        db.refresh(task)
        return task

    raise HTTPException(status_code=404, detail="Task not found")


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: DbSession):
    task = db.get(Task, task_id)
    if task is not None:
        db.delete(task)
        commit_changes(db)
        return

    raise HTTPException(status_code=404, detail="Task not found")
