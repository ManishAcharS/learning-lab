"""Explicitly migrate a legacy SQLite database to task ownership.

This project has no migration framework, and ``Base.metadata.create_all()``
cannot add the new non-nullable ``tasks.user_id`` column to an existing table.
This script performs the standard SQLite "new table, copy, rename" migration.

Safety rules:

* It never guesses an owner. You must pass exactly one of ``--user-id`` or
  ``--user-email`` for an already-registered user.
* It backs up the database file before changing anything.
* It refuses to continue if the ``users`` table or the selected user is missing.
* It runs the schema change and row copy in one transaction.
* ``--dry-run`` reports what would happen without modifying the database.

Usage (stop the API first):

    python migrate_task_ownership.py --user-email owner@example.com --dry-run
    python migrate_task_ownership.py --user-email owner@example.com

If the database has no users yet, start the API once so ``init_db()`` creates the
missing ``users`` table, register the intended owner, stop the API, then run this
script.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from database import DATABASE_PATH

NEW_TASKS_TABLE = """
CREATE TABLE tasks_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
    completed INTEGER NOT NULL DEFAULT 0
        CHECK(completed IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add and backfill tasks.user_id using an explicit owner.",
    )
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--user-id", type=int, help="Existing owner user ID.")
    identity.add_argument("--user-email", help="Existing owner email address.")
    parser.add_argument(
        "--database",
        type=Path,
        default=DATABASE_PATH,
        help=f"SQLite database file (default: {DATABASE_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the owner and row count without changing the database.",
    )
    return parser.parse_args()


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def resolve_owner(
    connection: sqlite3.Connection,
    user_id: int | None,
    user_email: str | None,
) -> tuple[int, str]:
    if user_id is not None:
        row = connection.execute(
            "SELECT id, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT id, email FROM users WHERE email = ?",
            (user_email.strip().lower(),),
        ).fetchone()

    if row is None:
        raise SystemExit(
            "No matching user found. Register the intended owner first; "
            "this migration will not invent or guess an owner."
        )
    return row[0], row[1]


def migrate(
    database_path: Path,
    *,
    user_id: int | None,
    user_email: str | None,
    dry_run: bool,
) -> None:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise SystemExit(f"Database file not found: {database_path}")

    connection = sqlite3.connect(database_path)
    try:
        if not table_exists(connection, "tasks"):
            print("No tasks table found; nothing to migrate.")
            return

        columns = column_names(connection, "tasks")
        if "user_id" in columns:
            print("tasks.user_id already exists; nothing to migrate.")
            return

        if not table_exists(connection, "users"):
            raise SystemExit(
                "The users table does not exist. Start the API once to create "
                "it, register the intended owner, then stop the API and rerun."
            )

        owner_id, owner_email = resolve_owner(
            connection,
            user_id,
            user_email,
        )
        task_count = connection.execute(
            "SELECT count(*) FROM tasks"
        ).fetchone()[0]

        if table_exists(connection, "tasks_new"):
            raise SystemExit(
                "A tasks_new table already exists. Inspect and remove it "
                "manually before retrying."
            )

        print(
            f"Will assign {task_count} existing task(s) to "
            f"user {owner_id} <{owner_email}>."
        )
        if dry_run:
            print("Dry run: no changes made.")
            return

        backup_path = database_path.with_name(
            f"{database_path.name}.bak-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(database_path, backup_path)
        print(f"Backup created: {backup_path}")

        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(NEW_TASKS_TABLE)
            connection.execute(
                """
                INSERT INTO tasks_new (id, title, completed, created_at, user_id)
                SELECT id, title, completed, created_at, ?
                FROM tasks
                """,
                (owner_id,),
            )
            connection.execute("DROP TABLE tasks")
            connection.execute("ALTER TABLE tasks_new RENAME TO tasks")
            connection.execute(
                "CREATE INDEX ix_tasks_user_id ON tasks(user_id)"
            )

            violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if violations:
                raise RuntimeError(
                    f"Foreign-key violations after migration: {violations}"
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise

        print(
            f"Migration complete. {task_count} task(s) now belong to "
            f"user {owner_id} <{owner_email}>."
        )
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    migrate(
        args.database,
        user_id=args.user_id,
        user_email=args.user_email,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
