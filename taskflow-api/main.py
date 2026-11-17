import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Task, User
from security import hash_password


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


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("password must not be empty or whitespace-only")
        return value


class UserRead(BaseModel):
    """Safe public user representation excluding secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(user_in: UserRegister, db: DbSession):
    # Check if email is already registered
    existing_user = db.scalar(select(User).where(User.email == user_in.email))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Hash the password with Argon2id; never persist plaintext
    hashed = hash_password(user_in.password)

    new_user = User(
        email=user_in.email,
        hashed_password=hashed,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error during user registration")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=DATABASE_ERROR_DETAIL,
        ) from None

    db.refresh(new_user)
    return new_user



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
    """Response shape for a task, including its database-generated timestamp."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    completed: bool
    created_at: datetime


SortField = Literal["id", "title", "completed"]
SortOrder = Literal["asc", "desc"]

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# Explicit whitelist: clients choose a name, never a SQL expression.
SORT_COLUMNS = {
    "id": Task.id,
    "title": Task.title,
    "completed": Task.completed,
}


def escape_like_pattern(value: str) -> str:
    """Treat LIKE wildcards in user input as literal characters."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/tasks", response_model=list[TaskRead])
def get_tasks(
    db: DbSession,
    response: Response,
    completed: bool | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: SortField = "id",
    sort_order: SortOrder = "asc",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = []

    # Filter in SQL; False must still apply, so compare explicitly to None.
    if completed is not None:
        filters.append(Task.completed == completed)

    if search is not None:
        pattern = f"%{escape_like_pattern(search)}%"
        filters.append(Task.title.ilike(pattern, escape="\\"))

    # Count using the same filters as the page query, before limit/offset.
    total = db.scalar(select(func.count()).select_from(Task).where(*filters)) or 0

    statement = select(Task).where(*filters)

    sort_column = SORT_COLUMNS[sort_by]
    if sort_order == "asc":
        statement = statement.order_by(sort_column.asc())
    else:
        statement = statement.order_by(sort_column.desc())

    # Ties get a stable, predictable order without changing the requested sort.
    if sort_by != "id":
        statement = statement.order_by(Task.id.asc())

    # Pagination belongs to the database query, never to Python slicing.
    statement = statement.offset(offset).limit(limit)

    tasks = db.scalars(statement).all()

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    return tasks


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
