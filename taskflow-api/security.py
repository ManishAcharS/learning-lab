"""Security utilities: JWT access-token mechanics and password hashing.

The signing key is never defined here. Callers must provide it explicitly, and
future API integration should load it from an environment variable such as
``TASKFLOW_JWT_SECRET``. Never commit a real secret or log credentials/tokens.

JWT payloads are signed, not encrypted: anyone holding a token can read its
claims. Only non-sensitive identifiers and timestamps belong in the payload.

Passwords are hashed using Argon2id via pwdlib, generating unique salts per hash.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_password_hasher = PasswordHash((Argon2Hasher(),))

JWT_ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
REQUIRED_CLAIMS = ("sub", "iat", "exp")


def _validate_secret_key(secret_key: str | bytes) -> None:
    """Reject missing keys instead of silently signing with an empty secret."""
    if not isinstance(secret_key, (str, bytes)) or not secret_key.strip():
        raise ValueError("secret_key must be a non-empty string or bytes")


def create_access_token(
    subject: str,
    secret_key: str | bytes,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed HS256 access token.

    Args:
        subject: Unique, non-empty identifier for the token's principal.
        secret_key: HMAC signing key supplied by the caller. API integration
            should load it from the ``TASKFLOW_JWT_SECRET`` environment
            variable rather than hardcoding it.
        expires_delta: Token lifetime. Defaults to 30 minutes.

    Returns:
        The encoded JWT as a string.

    Raises:
        ValueError: If ``subject`` or ``secret_key`` is empty, or if
            ``expires_delta`` is not a ``datetime.timedelta``.

    The payload contains only ``sub``, ``iat``, and ``exp``. Callers must
    never add passwords, password hashes, or other sensitive information.
    """
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string")

    _validate_secret_key(secret_key)

    if expires_delta is None:
        expires_delta = DEFAULT_ACCESS_TOKEN_EXPIRES
    elif not isinstance(expires_delta, timedelta):
        raise ValueError("expires_delta must be a datetime.timedelta")

    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": issued_at,
        "exp": issued_at + expires_delta,
    }

    return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(
    token: str,
    secret_key: str | bytes,
) -> dict[str, Any]:
    """Verify and decode a signed access token.

    The signature, expiration, issued-at, and subject claims are validated.
    Only HS256 is accepted, so the algorithm declared in the token header is
    never trusted.

    Args:
        token: Encoded JWT.
        secret_key: HMAC key used when the token was signed.

    Returns:
        The verified claims.

    Raises:
        jwt.InvalidTokenError: If the token is malformed, expired, tampered
            with, signed by another key or algorithm, or missing a valid
            subject. PyJWT's standard exception subclasses are preserved.
    """
    _validate_secret_key(secret_key)

    if not isinstance(token, str) or not token:
        raise jwt.InvalidTokenError("token must be a non-empty string")

    payload = jwt.decode(
        token,
        secret_key,
        algorithms=[JWT_ALGORITHM],
        options={"require": list(REQUIRED_CLAIMS)},
    )

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise jwt.InvalidTokenError("sub must be a non-empty string")

    return payload


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id with a unique random salt.

    Args:
        password: Raw password string.

    Returns:
        Argon2id password hash string.

    Raises:
        ValueError: If password is empty or not a valid string.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")

    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2id password hash.

    Args:
        plain_password: Raw password string.
        hashed_password: Stored hash string.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    if not isinstance(plain_password, str) or not plain_password:
        return False
    if not isinstance(hashed_password, str) or not hashed_password:
        return False

    try:
        return _password_hasher.verify(plain_password, hashed_password)
    except Exception:
        return False

