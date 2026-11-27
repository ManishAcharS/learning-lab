# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder: install the runtime dependencies into a self-contained virtualenv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only the dependency manifest is needed to build the image layer.
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime: minimal image with the virtualenv and application files only.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 10001 taskflow \
    && useradd --system --uid 10001 --gid taskflow \
        --home-dir /home/taskflow --shell /usr/sbin/nologin taskflow

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Copy only the modules the API needs, plus Alembic so migrations can be run
# inside the container. Never copy .env, .git, local databases, or tests.
COPY --chown=taskflow:taskflow \
    main.py database.py deps.py models.py security.py rate_limit.py ./
COPY --chown=taskflow:taskflow alembic ./alembic
COPY --chown=taskflow:taskflow alembic.ini ./

# Give the unprivileged user write access to the working directory so the
# SQLite fallback still works when DATABASE_URL is not configured.
RUN chown -R taskflow:taskflow /app

USER taskflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# Existing ASGI entry point: main.app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
