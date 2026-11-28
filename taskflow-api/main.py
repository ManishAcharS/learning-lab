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
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, init_db
from deps import (
    AUTHENTICATION_ERROR_DETAIL,
    get_current_active_user,
    get_jwt_secret,
)
from models import Comment, Task, User
from rate_limit import (
    RATE_LIMIT_ERROR_DETAIL,
    limiter,
    rate_limit_exceeded_handler,
)
from security import create_access_token, hash_password, verify_password


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables when the application starts. Existing tables are
    # left untouched; create_all does not perform schema migrations.
    init_db()
    yield


app = FastAPI(
    title="TaskFlow API",
    version="0.2.0",
    description=(
        "Task management REST API with JWT authentication, per-user task "
        "ownership, filtering, pagination, soft deletion, comments, and a "
        "database-aware health check."
    ),
    openapi_tags=[
        {
            "name": "Health",
            "description": "Unauthenticated API liveness and database readiness.",
        },
        {
            "name": "Authentication",
            "description": "Registration, login, and the authenticated profile.",
        },
        {
            "name": "Tasks",
            "description": (
                "Authenticated task CRUD, filtering, pagination, and soft-delete "
                "restore. Ownership is taken from the JWT and every query is "
                "scoped to the current user."
            ),
        },
        {
            "name": "Comments",
            "description": (
                "Authenticated comments on active tasks owned by the current user."
            ),
        },
    ],
    lifespan=lifespan,
)

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

UNAUTHORIZED_RESPONSE = {
    "description": "Missing, invalid, expired, or user-less Bearer token.",
    "content": {
        "application/json": {
            "example": {"detail": AUTHENTICATION_ERROR_DETAIL},
        }
    },
}
FORBIDDEN_RESPONSE = {
    "description": "The task exists but belongs to another user.",
    "content": {
        "application/json": {
            "example": {"detail": OWNERSHIP_ERROR_DETAIL},
        }
    },
}
NOT_FOUND_RESPONSE = {
    "description": "No active task exists with the requested ID.",
    "content": {
        "application/json": {
            "example": {"detail": "Task not found"},
        }
    },
}
VALIDATION_RESPONSE = {
    "description": "Request body, query, or path validation failed.",
    "content": {
        "application/json": {
            "example": {
                "error": "validation_error",
                "fields": [
                    {
                        "field": "title",
                        "message": "String should have at least 1 character",
                    }
                ],
            }
        }
    },
}
DATABASE_ERROR_RESPONSE = {
    "description": "A database operation failed; details are logged server-side.",
    "content": {
        "application/json": {
            "example": {"detail": DATABASE_ERROR_DETAIL},
        }
    },
}


class HealthResponse(BaseModel):
    """Safe health payload; never includes connection details."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "message": "TaskFlow api is running",
                "database": "connected",
            }
        }
    )

    status: Literal["healthy", "unhealthy"] = Field(
        description="Overall API health.",
        examples=["healthy"],
    )
    message: str = Field(
        description="Human-readable status message.",
        examples=["TaskFlow api is running"],
    )
    database: Literal["connected", "unavailable"] = Field(
        description="Result of the lightweight database connectivity check.",
        examples=["connected"],
    )


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


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Check API and database health",
    description=(
        "Returns API liveness together with a lightweight `SELECT 1` database "
        "readiness check. This endpoint is unauthenticated and never returns "
        "connection strings, credentials, or exception details."
    ),
    response_description="The API and database are reachable.",
    responses={
        503: {
            "description": "The API is running but the database is unreachable.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "unhealthy",
                        "message": "TaskFlow api is running",
                        "database": "unavailable",
                    }
                }
            },
        }
    },
)
def health(db: DbSession):
    """Report API liveness and database readiness.

    The query is deliberately tiny and unauthenticated. Failures return a
    generic 503 body: no exception text, connection string, or credentials are
    ever included in the response.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check database query failed")
        # End the failed transaction so nothing is reused by a later request.
        # A broken connection can also make rollback fail; the health response
        # must still be a generic 503 rather than a 500.
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.exception("Health check rollback failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "message": "TaskFlow api is running",
                "database": "unavailable",
            },
        )

    return {
        "status": "healthy",
        "message": "TaskFlow api is running",
        "database": "connected",
    }


class UserRegister(BaseModel):
    email: EmailStr = Field(
        description="Account email; stored lowercased and trimmed.",
        examples=["ada@example.com"],
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plaintext password (8-128 characters), hashed with Argon2id.",
        examples=["CorrectHorseBatteryStaple!"],
    )

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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "email": "ada@example.com",
                "created_at": "2026-11-28T10:15:00Z",
            }
        },
    )

    id: int = Field(description="Stable numeric user ID.", examples=[1])
    email: EmailStr = Field(
        description="Account email address.",
        examples=["ada@example.com"],
    )
    created_at: datetime = Field(
        description="Account creation timestamp.",
        examples=["2026-11-28T10:15:00Z"],
    )


@app.post(
    "/auth/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    summary="Register a new user",
    description=(
        "Creates an account with a unique email and an Argon2id password hash. "
        "Emails are normalized to lowercase. The response never includes the "
        "password or password hash."
    ),
    response_description="The newly created public user record.",
    responses={
        409: {
            "description": "The email is already registered.",
            "content": {
                "application/json": {
                    "example": {"detail": "Email already registered"},
                }
            },
        },
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
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

    access_token: str = Field(
        description="Signed HS256 JWT access token.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    token_type: str = Field(
        default="bearer",
        description="OAuth2 token type.",
        examples=["bearer"],
    )


LOGIN_ERROR_DETAIL = "Incorrect email or password"


@app.post(
    "/auth/login",
    response_model=Token,
    tags=["Authentication"],
    summary="Log in and obtain an access token",
    description=(
        "Authenticates an email/password pair using the OAuth2 password form. "
        "`username` carries the registered email address. Unknown emails and "
        "wrong passwords return the same generic 401 to prevent account "
        "enumeration. The endpoint is limited to five requests per minute per "
        "client IP."
    ),
    response_description="A Bearer access token for the authenticated user.",
    responses={
        401: {
            "description": "The email or password is incorrect.",
            "content": {
                "application/json": {
                    "example": {"detail": LOGIN_ERROR_DETAIL},
                }
            },
            "headers": {
                "WWW-Authenticate": {
                    "description": "Authentication scheme for the failed request.",
                    "schema": {"type": "string", "example": "Bearer"},
                }
            },
        },
        422: VALIDATION_RESPONSE,
        429: {
            "description": "The per-IP login rate limit was exceeded.",
            "content": {
                "application/json": {
                    "example": {"detail": RATE_LIMIT_ERROR_DETAIL},
                }
            },
            "headers": {
                "Retry-After": {
                    "description": "Seconds to wait before retrying.",
                    "schema": {"type": "string", "example": "60"},
                }
            },
        },
        500: {
            "description": "Server authentication is not configured.",
            "content": {
                "application/json": {
                    "example": {"detail": "Authentication is not configured"},
                }
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "required": ["username", "password"],
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Registered email address.",
                                "example": "ada@example.com",
                            },
                            "password": {
                                "type": "string",
                                "format": "password",
                                "description": "Account password.",
                                "example": "CorrectHorseBatteryStaple!",
                            },
                        },
                    },
                    "example": {
                        "username": "ada@example.com",
                        "password": "CorrectHorseBatteryStaple!",
                    },
                }
            },
        }
    },
)
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


@app.get(
    "/auth/me",
    response_model=UserRead,
    tags=["Authentication"],
    summary="Get the authenticated user's profile",
    description=(
        "Returns the safe public profile associated with the Bearer token. "
        "No password material is exposed."
    ),
    response_description="The authenticated user's public profile.",
    responses={401: UNAUTHORIZED_RESPONSE},
)
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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Prepare release notes",
                "description": "Summarize the v0.2.0 changes.",
                "status": "pending",
                "due_date": "2026-12-05",
                "completed": False,
            }
        }
    )

    title: str = Field(
        min_length=1,
        max_length=TITLE_MAX_LENGTH,
        description="Task title, 1-120 characters and not whitespace-only.",
        examples=["Prepare release notes"],
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
        description="Optional details up to 2,000 characters.",
        examples=["Summarize the v0.2.0 changes."],
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="API status; kept consistent with `completed`.",
        examples=["pending"],
    )
    due_date: date | None = Field(
        default=None,
        description="Optional due date; must be today or later.",
        examples=["2026-12-05"],
    )
    completed: bool = Field(
        default=False,
        description="Completion flag; must agree with `status` when both are sent.",
        examples=[False],
    )

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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Prepare v0.2.0 release notes",
                "status": "completed",
                "completed": True,
            }
        }
    )

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=TITLE_MAX_LENGTH,
        description="New title; omit to leave unchanged. Explicit null is rejected.",
        examples=["Prepare v0.2.0 release notes"],
    )
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
        description="New details; omit to leave unchanged.",
        examples=["Updated release checklist."],
    )
    status: TaskStatus | None = Field(
        default=None,
        description="New API status; omit to leave unchanged. Explicit null is rejected.",
        examples=["completed"],
    )
    due_date: date | None = Field(
        default=None,
        description="New due date; must be today or later when provided.",
        examples=["2026-12-10"],
    )
    completed: bool | None = Field(
        default=None,
        description="New completion flag; omit to leave unchanged.",
        examples=[True],
    )

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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 42,
                "title": "Prepare release notes",
                "description": "Summarize the v0.2.0 changes.",
                "status": "pending",
                "completed": False,
                "due_date": "2026-12-05",
                "created_at": "2026-11-28T10:15:00Z",
            }
        },
    )

    id: int = Field(description="Stable task ID.", examples=[42])
    title: str = Field(
        description="Task title.",
        examples=["Prepare release notes"],
    )
    description: str | None = Field(
        description="Optional task details.",
        examples=["Summarize the v0.2.0 changes."],
    )
    status: TaskStatus = Field(
        description="Derived API status.",
        examples=["pending"],
    )
    completed: bool = Field(
        description="Persisted completion flag.",
        examples=[False],
    )
    due_date: date | None = Field(
        description="Optional due date.",
        examples=["2026-12-05"],
    )
    created_at: datetime = Field(
        description="Database-generated creation timestamp.",
        examples=["2026-11-28T10:15:00Z"],
    )


COMMENT_BODY_MAX_LENGTH = 2000


class CommentCreate(BaseModel):
    """Comment input; ownership and the parent task come from auth and the URL."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"body": "Confirmed on staging; looks good to ship."}
        }
    )

    body: str = Field(
        min_length=1,
        max_length=COMMENT_BODY_MAX_LENGTH,
        description="Comment text, 1-2,000 characters and not whitespace-only.",
        examples=["Confirmed on staging; looks good to ship."],
    )

    @field_validator("body")
    @classmethod
    def reject_blank_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be empty or whitespace-only")
        return value


class CommentRead(BaseModel):
    """Safe public representation of a comment."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 7,
                "task_id": 42,
                "author_id": 1,
                "body": "Confirmed on staging; looks good to ship.",
                "created_at": "2026-11-28T10:20:00Z",
            }
        },
    )

    id: int = Field(description="Stable comment ID.", examples=[7])
    task_id: int = Field(description="Parent task ID.", examples=[42])
    author_id: int = Field(description="Author user ID.", examples=[1])
    body: str = Field(
        description="Comment text.",
        examples=["Confirmed on staging; looks good to ship."],
    )
    created_at: datetime = Field(
        description="Database-generated creation timestamp.",
        examples=["2026-11-28T10:20:00Z"],
    )


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


@app.get(
    "/tasks",
    response_model=list[TaskRead],
    tags=["Tasks"],
    summary="List, filter, search, sort, and paginate owned tasks",
    description=(
        "Returns only tasks owned by the authenticated user, excluding "
        "soft-deleted tasks. Filters, case-insensitive title search, sorting, "
        "counting, and pagination all run in the database. Pagination metadata "
        "is returned in `X-Total-Count`, `X-Limit`, and `X-Offset` headers."
    ),
    response_description="The requested page of owned tasks.",
    responses={
        200: {
            "description": "Owned tasks matching the filters and page window.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/TaskRead"},
                    },
                    "example": [
                        {
                            "id": 42,
                            "title": "Prepare release notes",
                            "description": "Summarize the v0.2.0 changes.",
                            "status": "pending",
                            "completed": False,
                            "due_date": "2026-12-05",
                            "created_at": "2026-11-28T10:15:00Z",
                        }
                    ],
                }
            },
            "headers": {
                "X-Total-Count": {
                    "description": "Filtered task count before limit/offset.",
                    "schema": {"type": "integer"},
                },
                "X-Limit": {
                    "description": "Maximum tasks in this response.",
                    "schema": {"type": "integer"},
                },
                "X-Offset": {
                    "description": "Number of matching tasks skipped.",
                    "schema": {"type": "integer"},
                },
            },
        },
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
def get_tasks(
    db: DbSession,
    current_user: CurrentUser,
    response: Response,
    completed: Annotated[
        bool | None,
        Query(description="Filter by completion state; omit for all tasks."),
    ] = None,
    search: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Case-insensitive title substring; wildcards are literal.",
        ),
    ] = None,
    sort_by: Annotated[
        SortField,
        Query(description="Column to sort by."),
    ] = "id",
    sort_order: Annotated[
        SortOrder,
        Query(description="Sort direction; ties are broken by ascending ID."),
    ] = "asc",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_PAGE_LIMIT,
            description="Page size (1-100).",
        ),
    ] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of matching tasks to skip."),
    ] = 0,
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


@app.post(
    "/tasks",
    response_model=TaskRead,
    status_code=201,
    tags=["Tasks"],
    summary="Create a task",
    description=(
        "Creates a task owned by the authenticated user. Ownership always comes "
        "from the verified JWT, never the request body. Status and `completed` "
        "must agree when both are supplied."
    ),
    response_description="The newly created task.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
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


@app.get(
    "/tasks/{task_id}",
    response_model=TaskRead,
    tags=["Tasks"],
    summary="Get one owned task",
    description=(
        "Returns a single active task when it belongs to the authenticated user. "
        "Soft-deleted tasks are treated as missing."
    ),
    response_description="The requested owned task.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
def get_task(task_id: int, db: DbSession, current_user: CurrentUser):
    return get_owned_task(db, task_id, current_user)


@app.patch(
    "/tasks/{task_id}",
    response_model=TaskRead,
    tags=["Tasks"],
    summary="Partially update an owned task",
    description=(
        "Updates only the supplied fields on an active task owned by the "
        "authenticated user. Omitted fields are unchanged; explicit JSON null "
        "is rejected for non-nullable fields. Ownership cannot be changed."
    ),
    response_description="The updated task.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
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


@app.delete(
    "/tasks/{task_id}",
    status_code=204,
    tags=["Tasks"],
    summary="Soft-delete an owned task",
    description=(
        "Marks an active task owned by the authenticated user as deleted by "
        "setting `deleted_at`. The row is retained so restore is possible. "
        "Repeating the delete returns 404 and does not overwrite the timestamp."
    ),
    response_description="The task was soft-deleted; the response has no body.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
def delete_task(task_id: int, db: DbSession, current_user: CurrentUser):
    """Soft-delete an owned, active task.

    The row is kept and ``deleted_at`` records when it was removed from the
    active set. A repeated delete finds no active task and keeps the original
    404 response, so the first deletion timestamp is never overwritten.
    """
    task = get_owned_task(db, task_id, current_user)
    task.deleted_at = datetime.now(timezone.utc)
    commit_changes(db)


@app.post(
    "/tasks/{task_id}/restore",
    response_model=TaskRead,
    tags=["Tasks"],
    summary="Restore a soft-deleted owned task",
    description=(
        "Clears `deleted_at` on a task owned by the authenticated user. Restore "
        "is idempotent: an already-active task is returned unchanged. Another "
        "user's task returns 403; an unknown ID returns 404."
    ),
    response_description="The restored or already-active task.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
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
    tags=["Comments"],
    summary="Add a comment to an owned task",
    description=(
        "Creates a comment on an active task owned by the authenticated user. "
        "The author always comes from the JWT; task access checks reject "
        "missing or deleted tasks with 404 and other users' tasks with 403."
    ),
    response_description="The newly created comment.",
    responses={
        401: UNAUTHORIZED_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
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


@app.get(
    "/tasks/{task_id}/comments",
    response_model=list[CommentRead],
    tags=["Comments"],
    summary="List an owned task's comments",
    description=(
        "Returns comments for an active task owned by the authenticated user, "
        "newest first, with offset pagination. Pagination metadata is returned "
        "in `X-Total-Count`, `X-Limit`, and `X-Offset` headers."
    ),
    response_description="The requested page of comments, newest first.",
    responses={
        200: {
            "description": "Comments for the owned task, newest first.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/CommentRead"},
                    },
                    "example": [
                        {
                            "id": 7,
                            "task_id": 42,
                            "author_id": 1,
                            "body": "Confirmed on staging; looks good to ship.",
                            "created_at": "2026-11-28T10:20:00Z",
                        }
                    ],
                }
            },
            "headers": {
                "X-Total-Count": {
                    "description": "Total comments on the task before limit/offset.",
                    "schema": {"type": "integer"},
                },
                "X-Limit": {
                    "description": "Maximum comments in this response.",
                    "schema": {"type": "integer"},
                },
                "X-Offset": {
                    "description": "Number of comments skipped.",
                    "schema": {"type": "integer"},
                },
            },
        },
        401: UNAUTHORIZED_RESPONSE,
        403: FORBIDDEN_RESPONSE,
        404: NOT_FOUND_RESPONSE,
        422: VALIDATION_RESPONSE,
        500: DATABASE_ERROR_RESPONSE,
    },
)
def get_task_comments(
    task_id: int,
    db: DbSession,
    current_user: CurrentUser,
    response: Response,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_PAGE_LIMIT,
            description="Page size (1-100).",
        ),
    ] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of comments to skip."),
    ] = 0,
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
