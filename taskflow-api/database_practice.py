
import sqlite3

# Connect to a local database file.
# SQLite creates the file if it doesn't exist.
connection = sqlite3.connect("taskflow.db")
cursor = connection.cursor()

# Create the table and enforce basic data rules.
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
        completed INTEGER NOT NULL DEFAULT 0
            CHECK(completed IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
""")

# Insert sample data only when the table is empty.
cursor.execute("SELECT COUNT(*) FROM tasks")
count = cursor.fetchone()[0]

if count == 0:
    cursor.executemany(
        "INSERT INTO tasks (title, completed) VALUES (?, ?)",
        [
            ("Learn SQL", 0),
            ("Build TaskFlow", 1),
            ("Practise database queries", 0),
        ],
    )

connection.commit()

# SELECT: retrieve every task.
print("\nAll tasks:")
cursor.execute("SELECT id, title, completed, created_at FROM tasks")
for task in cursor.fetchall():
    print(task)

# WHERE: retrieve one task by ID.
print("\nTask with ID 2:")
cursor.execute("SELECT id, title FROM tasks WHERE id = ?", (2,))
print(cursor.fetchone())

# ORDER BY: sort tasks by ID, newest ID first.
print("\nTasks ordered by ID:")
cursor.execute("SELECT id, title FROM tasks ORDER BY id DESC")
for task in cursor.fetchall():
    print(task)

connection.close()
