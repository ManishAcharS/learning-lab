"""
TaskFlow SQL Practice
--------------------
Run this file from your taskflow-api folder:

    python sql_practice.py

It creates taskflow.db (if needed), creates a tasks table, adds sample
records only when the table is empty, and opens a small SQL practice prompt.

Type SQL statements at the prompt. Examples:
    SELECT * FROM tasks;
    SELECT * FROM tasks WHERE completed = 1;

Type .exit to quit.
"""

import sqlite3
from pathlib import Path

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
    cursor.execute(sql)

    if cursor.description is None:
        print(f"Query executed. Rows affected: {cursor.rowcount}")
        return

    rows = cursor.fetchall()
    columns = [column[0] for column in cursor.description]

    print("\n" + " | ".join(columns))
    print("-" * max(20, len(" | ".join(columns))))

    if not rows:
        print("(no rows returned)")
    else:
        for row in rows:
            print(" | ".join(str(value) for value in row))

    print(f"\n{len(rows)} row(s) returned.")


def main():
    conn = setup_database()
    cursor = conn.cursor()

    print("\nTaskFlow SQL Practice")
    print(f"Database: {DB_PATH}")
    print("Enter one SQL query per line. Type .exit to quit.")
    print("Tip: SQL statements should end with a semicolon.\n")

    try:
        while True:
            sql = input("SQL> ").strip()

            if sql.lower() in {".exit", "exit", "quit"}:
                break

            if not sql:
                continue

            try:
                run_query(cursor, sql)
                conn.commit()
            except sqlite3.Error as error:
                print(f"SQLite error: {error}")

    except (KeyboardInterrupt, EOFError):
        print("\nExiting SQL practice.")

    finally:
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()
