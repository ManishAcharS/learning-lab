"""Alembic environment for TaskFlow.

The application stores its database URL in ``database.py``. Migrations use the
same URL by default, but ``TASKFLOW_DATABASE_URL`` can point a migration run at
a disposable database (for example, when testing an upgrade/downgrade cycle).
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from database import DATABASE_URL, Base
from models import Task, User  # noqa: F401  (register tables on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ``TASKFLOW_DATABASE_URL`` is only for migration tooling and tests. The
# application itself continues to use ``database.DATABASE_URL``.
database_url = os.getenv("TASKFLOW_DATABASE_URL", DATABASE_URL)
# ConfigParser treats percent signs as interpolation markers.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without a live DBAPI connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
