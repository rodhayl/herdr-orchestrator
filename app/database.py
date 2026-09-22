"""SQLite database management and task operations for MiniBoard."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

VALID_STATUSES = ("TODO", "DOING", "DONE")
DEFAULT_STATUS = "TODO"


@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Provide a transactional SQLite database connection."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    """Initialize the SQLite database schema if not already present."""
    if db_path != ":memory:":
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('TODO', 'DOING', 'DONE')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)


def _get_utc_timestamp() -> str:
    """Return the current UTC timestamp formatted as ISO-8601 YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert an sqlite3.Row into a standard task dictionary."""
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_all_tasks(db_path: str) -> list[dict[str, Any]]:
    """Retrieve all tasks ordered by id ascending."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, status, created_at, updated_at FROM tasks ORDER BY id ASC;")
        rows = cursor.fetchall()
        return [_row_to_dict(row) for row in rows]


def get_task(db_path: str, task_id: int) -> Optional[dict[str, Any]]:
    """Retrieve a single task by ID, or None if not found."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, status, created_at, updated_at FROM tasks WHERE id = ?;", (task_id,))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None


get_task_by_id = get_task


def create_task(db_path: str, title: str, status: str = DEFAULT_STATUS) -> dict[str, Any]:
    """Create a new task and persist it to the SQLite database."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Title is required and must be a non-empty string")
    trimmed_title = title.strip()

    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

    now = _get_utc_timestamp()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tasks (title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?);
            """,
            (trimmed_title, status, now, now),
        )
        task_id = cursor.lastrowid
        cursor.execute(
            "SELECT id, title, status, created_at, updated_at FROM tasks WHERE id = ?;",
            (task_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(row)


def update_task(
    db_path: str,
    task_id: int,
    title: Optional[str] = None,
    status: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Partially update an existing task's title, status, or both."""
    if title is None and status is None:
        raise ValueError("Invalid update payload")

    trimmed_title: Optional[str] = None
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Invalid update payload")
        trimmed_title = title.strip()

    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError("Invalid update payload")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tasks WHERE id = ?;", (task_id,))
        if cursor.fetchone() is None:
            return None

        now = _get_utc_timestamp()
        updates: list[str] = []
        params: list[Any] = []

        if trimmed_title is not None:
            updates.append("title = ?")
            params.append(trimmed_title)

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        updates.append("updated_at = ?")
        params.append(now)

        params.append(task_id)

        sql = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?;"
        cursor.execute(sql, tuple(params))

        cursor.execute(
            "SELECT id, title, status, created_at, updated_at FROM tasks WHERE id = ?;",
            (task_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None


def delete_task(db_path: str, task_id: int) -> bool:
    """Delete a task by ID. Return True if deleted, False if not found."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tasks WHERE id = ?;", (task_id,))
        if cursor.fetchone() is None:
            return False
        cursor.execute("DELETE FROM tasks WHERE id = ?;", (task_id,))
        return True
