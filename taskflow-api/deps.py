"""Reusable FastAPI authentication dependencies.

Access tokens are issued by ``POST /auth/login`` and use the OAuth2 password
flow. The JWT ``sub`` claim is the decimal string form of ``User.id``;
registration returns numeric user IDs, and user IDs are stable even if an email
changes.

The signing key is read from ``TASKFLOW_JWT_SECRET`` for each request. There is
deliberately no fallback secret: a missing configuration is a deployment error.
"""

import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User
from security import decode_access_token

JWT_SECRET_ENV_VAR = "TASKFLOW_JWT_SECRET"

# ``auto_error=False`` keeps the dependency's single generic 401 response for
# missing, malformed, and non-Bearer credentials. The token URL is the actual
# mounted login route so OpenAPI's "Authorize" flow works.
bearer_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    auto_error=False,
)

DbSession = Annotated[Session, Depends(get_db)]
AccessToken = Annotated[
    str | None,
    Depends(bearer_scheme),
]

AUTHENTICATION_ERROR_DETAIL = "Could not validate credentials"


def _unauthorized() -> HTTPException:
    """Return one generic 401 response without leaking token details."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTHENTICATION_ERROR_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_jwt_secret() -> str:
    """Load the JWT signing key from the environment.

    No default is provided, so a missing or blank environment variable cannot
    silently fall back to a predictable production secret.
    """
    secret = os.getenv(JWT_SECRET_ENV_VAR)
    if not secret or not secret.strip():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is not configured",
        )
    return secret


def get_current_active_user(
    credentials: AccessToken,
    db: DbSession,
) -> User:
    """Return the registered user identified by a valid Bearer JWT.

    Identity comes only from the verified token subject. Request bodies, query
    parameters, and caller-supplied headers are never used to choose a user.

    Raises:
        HTTPException: 401 with ``WWW-Authenticate: Bearer`` when the token is
            missing, malformed, expired, tampered with, signed by another key,
            has an invalid subject, or references a user that does not exist.
    """
    if credentials is None:
        raise _unauthorized()

    secret = get_jwt_secret()

    try:
        payload = decode_access_token(credentials, secret)
    except jwt.InvalidTokenError:
        raise _unauthorized() from None

    subject = payload.get("sub")
    if (
        not isinstance(subject, str)
        or not subject.isdecimal()
        or len(subject) > 19
    ):
        raise _unauthorized()

    user_id = int(subject)
    if user_id <= 0 or user_id > 2**63 - 1:
        raise _unauthorized()

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized()

    return user
