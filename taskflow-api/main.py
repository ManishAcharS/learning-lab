import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, init_db
from deps import get_current_active_user, get_jwt_secret
from models import Comment, Task, User
from rate_limit import limiter, rate_limit_exceeded_handler
from security import create_access_token, hash_password, verify_password


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables when the application starts. Existing tables are
    # left untouched; create_all does not perform schema migrations.
    init_db()
    yield


app = FastAPI(title="Taskflow API", lifespan=lifespan)

# SlowAPI keeps its limiter on app.state and needs the matching exception
# handler for RateLimitExceeded. Only decorated routes consume the limit.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

VALIDATION_ERROR_CODE = "validation_error"
VALIDATION_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}


def format_validation_field(location: tuple[object, ...]) -> str:
    """Turn a Pydantic error location into a stable public field path."""
    # Strip only FastAPI's leading request location (body/query/path/...), so a
    # real field that happens to be named like one of those keeps its name.
    parts = list(location)
    if parts and parts[0] in VALIDATION_LOCATION_PREFIXES:
        parts = parts[1:]
    if not parts:
        return "request"

    field = ""
    for part in parts:
        if isinstance(part, int):
            field += f"[{part}]"
        else:
            field = f"{field}.{part}" if field else str(part)
    return field


def readable_validation_message(error: dict) -> str:
    """Use Pydantic's message text without exposing inputs or exception objects."""
    message = str(error.get("msg", "Invalid value"))
    # Pydantic prefixes custom validator failures with this internal wording.
    if message.startswith("Value error, "):
        message = message[len("Value error, "):]
    return message


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
):
    """Return one consistent 422 shape for every endpoint's validation errors."""
    fields = [
        {
            "field": format_validation_field(tuple(error.get("loc", ()))),
            "message": readable_validation_message(error),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": VALIDATION_ERROR_CODE,
            "fields": fields,
        },
    )

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]

logger = logging.getLogger(__name__)
DATABASE_ERROR_DETAIL = "Database operation failed"
OWNERSHIP_ERROR_DETAIL = "Not authorized to access this task"


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


class Token(BaseModel):
    """OAuth2-compatible access-token response; contains no user secrets."""

    access_token: str
    token_type: str = "bearer"


LOGIN_ERROR_DETAIL = "Incorrect email or password"


@app.post("/auth/login", response_model=Token)
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    secret: Annotated[str, Depends(get_jwt_secret)],
):
    """Authenticate an email/password pair and issue a Bearer access token.

    ``username`` carries the registered email address. Unknown emails and wrong
    passwords produce the same generic 401 so the endpoint cannot be used to
    enumerate accounts.

    The endpoint is limited to five requests per minute per client IP. The
    ``request`` parameter is required by SlowAPI, and ``response`` lets SlowAPI
    attach rate-limit headers to successful responses.
    """
    # Match registration's normalization so case/whitespace variants still log in.
    email = form_data.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(
        form_data.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_ERROR_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Existing contract: the JWT subject is the decimal string form of User.id.
    access_token = create_access_token(str(user.id), secret)
    return Token(access_token=access_token, token_type="bearer")


@app.get("/auth/me", response_model=UserRead)
def get_me(current_user: Annotated[User, Depends(get_current_active_user)]):
    """Return safe profile data for the authenticated user."""
    return current_user


class TaskStatus(str, Enum):
    """Task states supported by the existing binary ``completed`` field."""

    PENDING = "pending"
    COMPLETED = "completed"


TITLE_MAX_LENGTH = 120
DESCRIPTION_MAX_LENGTH = 2000


def validate_due_date(value: date | None) -> date | None:
    """Reject due dates before the server's current local date."""
    if value is not None and value < date.today():
        raise ValueError("due_date must be today or later")
    return value


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    status: TaskStatus = TaskStatus.PENDING
    due_date: date | None = None
    completed: bool = False

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty or whitespace-only")
        return value

    @field_validator("due_date")
    @classmethod
    def validate_create_due_date(cls, value: date | None) -> date | None:
        return validate_due_date(value)

    @model_validator(mode="after")
    def reconcile_status_and_completed(self):
        """Keep the API status and the persisted boolean consistent."""
        if "status" in self.model_fields_set:
            expected_completed = self.status is TaskStatus.COMPLETED
            if (
                "completed" in self.model_fields_set
                and self.completed != expected_completed
            ):
                raise ValueError("completed must match status")
            self.completed = expected_completed
        return self


class TaskUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=TITLE_MAX_LENGTH,
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
    )
    status: TaskStatus | None = None
    due_date: date | None = None
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

    @field_validator("status")
    @classmethod
    def reject_explicit_null_status(cls, value):
        if value is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        return value

    @field_validator("due_date")
    @classmethod
    def validate_update_due_date(cls, value: date | None) -> date | None:
        return validate_due_date(value)

    @field_validator("completed")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("must not be null; omit the field to leave it unchanged")
        return value

    @model_validator(mode="after")
    def reconcile_status_and_completed(self):
        if (
            "status" in self.model_fields_set
            and "completed" in self.model_fields_set
            and self.completed != (self.status is TaskStatus.COMPLETED)
        ):
            raise ValueError("completed must match status")
        return self


class TaskRead(BaseModel):
    """Response shape for a task, including its database-generated timestamp."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: TaskStatus
    completed: bool
    due_date: date | None
    created_at: datetime


COMMENT_BODY_MAX_LENGTH = 2000


class CommentCreate(BaseModel):
    """Comment input; ownership and the parent task come from auth and the URL."""

    body: str = Field(min_length=1, max_length=COMMENT_BODY_MAX_LENGTH)

    @field_validator("body")
    @classmethod
    def reject_blank_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be empty or whitespace-only")
        return value


class CommentRead(BaseModel):
    """Safe public representation of a comment."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    author_id: int
    body: str
    created_at: datetime


def get_owned_task(
    db: Session,
    task_id: int,
    current_user: User,
    *,
    include_deleted: bool = False,
) -> Task:
    """Return a task only when it belongs to ``current_user``.

    A missing task keeps the existing 404 behavior. An existing task owned by
    someone else returns 403 without exposing its contents or owner details.
    Soft-deleted tasks are treated as missing unless ``include_deleted`` is set,
    which restore uses so it can find the owner's deleted task.
    """
    task = db.get(Task, task_id)
    if task is None or (task.deleted_at is not None and not include_deleted):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    if task.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=OWNERSHIP_ERROR_DETAIL,
        )
    return task


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
    current_user: CurrentUser,
    response: Response,
    completed: bool | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: SortField = "id",
    sort_order: SortOrder = "asc",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    # Ownership is part of every query, including the count, so users can never
    # observe another user's tasks through listing, search, or pagination.
    # Soft-deleted tasks are excluded before every other filter is applied.
    filters = [
        Task.user_id == current_user.id,
        Task.deleted_at.is_(None),
    ]

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
def create_task(task: TaskCreate, db: DbSession, current_user: CurrentUser):
    # Ownership always comes from the verified token, never the request body.
    new_task = Task(
        title=task.title,
        description=task.description,
        completed=task.completed,
        due_date=task.due_date,
        user_id=current_user.id,
    )
    db.add(new_task)
    commit_changes(db)
    db.refresh(new_task)
    return new_task


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: DbSession, current_user: CurrentUser):
    return get_owned_task(db, task_id, current_user)


@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    update: TaskUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    task = get_owned_task(db, task_id, current_user)

    # Keep omitted fields unchanged during a partial update. TaskUpdate only
    # exposes task-owned fields, so user_id can never be changed by a request.
    changes = update.model_dump(exclude_unset=True)
    status_value = changes.pop("status", None)
    if status_value is not None:
        changes["completed"] = status_value is TaskStatus.COMPLETED
    for field, value in changes.items():
        setattr(task, field, value)

    commit_changes(db)
    db.refresh(task)
    return task


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: DbSession, current_user: CurrentUser):
    """Soft-delete an owned, active task.

    The row is kept and ``deleted_at`` records when it was removed from the
    active set. A repeated delete finds no active task and keeps the original
    404 response, so the first deletion timestamp is never overwritten.
    """
    task = get_owned_task(db, task_id, current_user)
    task.deleted_at = datetime.now(timezone.utc)
    commit_changes(db)


@app.post("/tasks/{task_id}/restore", response_model=TaskRead)
def restore_task(task_id: int, db: DbSession, current_user: CurrentUser):
    """Restore an owned, soft-deleted task by clearing ``deleted_at``.

    Restore is idempotent: restoring a task that is already active returns it
    unchanged. A task owned by another user follows the existing 403 ownership
    response, while a task that never existed returns 404.
    """
    task = get_owned_task(db, task_id, current_user, include_deleted=True)
    if task.deleted_at is not None:
        task.deleted_at = None
        commit_changes(db)
        db.refresh(task)
    return task


@app.post(
    "/tasks/{task_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    task_id: int,
    comment: CommentCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    """Add a comment to an active task owned by the authenticated user."""
    # Reuse task access control: missing/deleted tasks are 404, other owners 403.
    task = get_owned_task(db, task_id, current_user)

    new_comment = Comment(
        task_id=task.id,
        author_id=current_user.id,
        body=comment.body,
    )
    db.add(new_comment)
    commit_changes(db)
    db.refresh(new_comment)
    return new_comment


@app.get("/tasks/{task_id}/comments", response_model=list[CommentRead])
def get_task_comments(
    task_id: int,
    db: DbSession,
    current_user: CurrentUser,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List an active task's comments, newest first, using offset pagination."""
    task = get_owned_task(db, task_id, current_user)

    filters = [Comment.task_id == task.id]
    total = db.scalar(
        select(func.count()).select_from(Comment).where(*filters)
    ) or 0

    statement = (
        select(Comment)
        .where(*filters)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .offset(offset)
        .limit(limit)
    )
    comments = db.scalars(statement).all()

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    return comments
