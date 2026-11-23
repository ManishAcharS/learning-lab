"""Per-IP rate limiting for TaskFlow authentication endpoints.

The limiter uses the request's socket peer address (``request.client.host``).
It deliberately does not read ``X-Forwarded-For`` or similar headers: those are
client-controlled unless the application runs behind an explicitly trusted
proxy that sanitizes them.

Storage is in-memory, so each application process has its own counters. Workers
or multiple instances do not share rate-limit state; a shared backend such as
Redis would be required for multi-process enforcement.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

RATE_LIMIT_ERROR_DETAIL = "Rate limit exceeded"

# headers_enabled=True makes SlowAPI add Retry-After and X-RateLimit-* headers.
# The login endpoint therefore also accepts a Response parameter for successful
# requests, as required by SlowAPI when header injection is enabled.
limiter = Limiter(
    key_func=get_remote_address,
    headers_enabled=True,
)


def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    """Return the API's consistent 429 body plus SlowAPI's rate-limit headers."""
    response = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": RATE_LIMIT_ERROR_DETAIL},
    )

    # SlowAPI records the limit that was hit on request.state. Reuse its header
    # injection so Retry-After reflects the actual current window.
    current_limit = getattr(request.state, "view_rate_limit", None)
    if current_limit is not None:
        response = request.app.state.limiter._inject_headers(
            response,
            current_limit,
        )

    # Conservative fallback for the one-minute limit if header injection ever
    # cannot calculate a window (for example, a future storage backend error).
    if "Retry-After" not in response.headers:
        response.headers["Retry-After"] = "60"

    return response
