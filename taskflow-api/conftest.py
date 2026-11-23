"""Shared pytest fixtures for TaskFlow tests."""

import pytest

from rate_limit import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Give every test an isolated in-memory rate-limit state.

    Rate-limit counters are process-global because the limiter uses in-memory
    storage. Resetting before and after each test prevents one test's login
    requests from causing unrelated tests to receive 429 responses.
    """
    limiter.reset()
    yield
    limiter.reset()
