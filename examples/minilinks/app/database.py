"""Database operations and SQLite management for MiniLinks."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = "minilinks.db"


def get_utc_now() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates and returns a SQLite connection with Row factory."""
    parent = Path(db_path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Initializes the SQLite database at `db_path`, creating the bookmarks table
    and ensuring any parent directories exist.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
    finally:
        conn.close()


def get_bookmarks(
    q: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    Retrieves all bookmarks, optionally filtered by search term `q` across
    title, url, and notes (case-insensitive substring match).
    Bookmarks are returned ordered by id ASC.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        if q is not None and q.strip() != "":
            query_str = q.strip().lower()
            escaped = (
                query_str.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            cursor.execute(
                """
                SELECT id, title, url, notes, created_at, updated_at
                FROM bookmarks
                WHERE LOWER(COALESCE(title, '')) LIKE ? ESCAPE '\\'
                   OR LOWER(COALESCE(url, '')) LIKE ? ESCAPE '\\'
                   OR LOWER(COALESCE(notes, '')) LIKE ? ESCAPE '\\'
                ORDER BY id ASC
                """,
                (pattern, pattern, pattern),
            )
        else:
            cursor.execute(
                """
                SELECT id, title, url, notes, created_at, updated_at
                FROM bookmarks
                ORDER BY id ASC
                """
            )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "notes": row["notes"] if row["notes"] is not None else "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_bookmark_by_id(
    id: Optional[int] = None,
    db_path: str = DEFAULT_DB_PATH,
    *,
    bookmark_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single bookmark by ID, or None if not found."""
    target_id = id if id is not None else bookmark_id
    if target_id is None:
        return None

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, url, notes, created_at, updated_at
            FROM bookmarks
            WHERE id = ?
            """,
            (target_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "notes": row["notes"] if row["notes"] is not None else "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def create_bookmark(
    title: str,
    url: str,
    notes: Optional[str] = "",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Creates a new bookmark with title, url, and optional notes.
    Sets created_at and updated_at to the current UTC timestamp.
    """
    now_iso = get_utc_now()
    notes_val = notes if notes is not None else ""

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO bookmarks (title, url, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title, url, notes_val, now_iso, now_iso),
            )
            created_id = cursor.lastrowid

        return {
            "id": created_id,
            "title": title,
            "url": url,
            "notes": notes_val,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    finally:
        conn.close()


def update_bookmark(
    id: Optional[int] = None,
    title: Optional[str] = None,
    url: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
    *,
    bookmark_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Updates an existing bookmark's title, url, and/or notes.
    Updates the updated_at timestamp to current UTC time.
    Returns the complete updated bookmark record, or None if not found.
    """
    target_id = id if id is not None else bookmark_id
    if target_id is None:
        return None

    existing = get_bookmark_by_id(target_id, db_path=db_path)
    if existing is None:
        return None

    updates = []
    params: List[Any] = []

    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if url is not None:
        updates.append("url = ?")
        params.append(url)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)

    if not updates:
        return existing

    now_iso = get_utc_now()
    updates.append("updated_at = ?")
    params.append(now_iso)
    params.append(target_id)

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE bookmarks SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            cursor.execute(
                """
                SELECT id, title, url, notes, created_at, updated_at
                FROM bookmarks
                WHERE id = ?
                """,
                (target_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "notes": row["notes"] if row["notes"] is not None else "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
    finally:
        conn.close()


def delete_bookmark(
    id: Optional[int] = None,
    db_path: str = DEFAULT_DB_PATH,
    *,
    bookmark_id: Optional[int] = None,
) -> bool:
    """Deletes a bookmark by ID. Returns True if deleted, False if not found."""
    target_id = id if id is not None else bookmark_id
    if target_id is None:
        return False

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bookmarks WHERE id = ?", (target_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()
