"""Baseline schema for TaskFlow before task soft deletion.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25 00:00:00.000000

This project previously had no Alembic history. This baseline captures the
existing users/tasks schema so later schema changes can use normal revisions.
Databases created before Alembic was introduced can be adopted with
``alembic stamp 0001_initial_schema`` instead of re-running this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the users and tasks tables exactly as they existed pre-change."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "completed",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 120",
            name="ck_tasks_title_length",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"], unique=False)


def downgrade() -> None:
    """Remove the baseline tables."""
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
