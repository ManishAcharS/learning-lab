
"""
TaskFlow SQL Practice
---------------------

Run this file from your taskflow-api folder:

    python sql_practice.py

Features:
- Connects to taskflow.db
- Creates the tasks table if it doesn't exist
- Inserts sample records only when the table is empty
- Provides an interactive SQL practice prompt
- Displays SELECT query results
- Reports affected rows
- Commits successful queries
- Rolls back failed queries
- Closes the database connection safely

Type .exit to quit.
"""

import sqlite3
from pathlib import Path


# Use the same folder as this Python file.
DB_PATH = Path(__file__).with_name("taskflow.db")


SAMPLE_TASKS = [
    ("Learn SQL", 0),
    ("Build TaskFlow API", 1),
    ("Practise Python", 0),
    ("Write API tests", 1),
    ("Read FastAPI docs", 0),
    ("Review database basics", 1),
]


def setup_database():
    """Connect to the database and prepare the tasks table."""

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0
                CHECK (completed IN (0, 1))
        )
    """)

    # Verify that the existing table has the expected columns.
    cursor.execute("PRAGMA table_info(tasks)")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = {"id", "title", "completed"}

    if not required_columns.issubset(columns):
        conn.close()
        raise RuntimeError(
            "Your existing tasks table has an incompatible schema. "
            "Inspect it before running SQL practice."
        )

    # Insert sample tasks only if the table is empty.
    cursor.execute("SELECT COUNT(*) FROM tasks")
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.executemany(
            "INSERT INTO tasks (title, completed) VALUES (?, ?)",
            SAMPLE_TASKS,
        )

        conn.commit()
        print(f"Added {len(SAMPLE_TASKS)} sample tasks.")

    return conn


def run_query(cursor, sql):
    """Execute a SQL statement and display its results."""

    cursor.execute(sql)

    # Check whether the query returns rows.
    if cursor.description is None:
        print(
            f"Query executed successfully. "
            f"Rows affected: {cursor.rowcount}"
        )
        return

    rows = cursor.fetchall()

    columns = [
        column[0]
        for column in cursor.description
    ]

    header = " | ".join(columns)

    print("\n" + header)
    print("-" * max(20, len(header)))

    if not rows:
        print("(no rows returned)")
    else:
        for row in rows:
            print(" | ".join(str(value) for value in row))

    print(f"\n{len(rows)} row(s) returned.")


def main():
    """Start the SQL practice environment."""

    conn = setup_database()
    cursor = conn.cursor()

    print("\n========== TaskFlow SQL Practice ==========")
    print(f"Database: {DB_PATH}")
    print("\nEnter one SQL statement per line.")
    print("Type .exit to quit.")
    print("\nExample:")
    print("SELECT * FROM tasks;")
    print("UPDATE tasks SET completed = 1 WHERE id = 1;")
    print("============================================\n")

    try:
        while True:
            sql = input("SQL> ").strip()

            if sql.lower() in {".exit", "exit", "quit"}:
                break

            if not sql:
                continue

            try:
                run_query(cursor, sql)

                # Save successful database changes.
                conn.commit()

                print("Transaction committed.")

            except sqlite3.Error as error:

                # Undo unsuccessful uncommitted changes.
                conn.rollback()

                print(f"\nSQLite error: {error}")
                print("Transaction rolled back.")

    except (KeyboardInterrupt, EOFError):
        print("\nExiting SQL practice.")

    finally:
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()
