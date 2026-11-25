"""Add nullable tasks.deleted_at for soft deletion.

Revision ID: 0002_add_task_deleted_at
Revises: 0001_initial_schema
Create Date: 2026-11-25 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_add_task_deleted_at"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable soft-delete marker; existing rows stay active."""
    op.add_column(
        "tasks",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove only the soft-delete marker; task rows are left intact."""
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("deleted_at")
