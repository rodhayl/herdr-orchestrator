"""Database operations and SQLite management for MiniLinks."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union

DEFAULT_DB_PATH = "minilinks.db"


def get_utc_now() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_connection(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates and returns a SQLite connection with Row factory."""
    db_path_str = str(db_path)
    parent = Path(db_path_str).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path_str, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_notes_column(conn: sqlite3.Connection) -> None:
    """Adds notes column to bookmarks table if missing (backward compatibility)."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(bookmarks)")
    cols = [row[1] for row in cursor.fetchall()]
    if cols and "notes" not in cols:
        cursor.execute("ALTER TABLE bookmarks ADD COLUMN notes TEXT DEFAULT ''")
        cursor.execute("UPDATE bookmarks SET notes = '' WHERE notes IS NULL")


def _migrate_tags_column(conn: sqlite3.Connection) -> None:
    """Adds tags column to bookmarks table if missing (backward compatibility)."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(bookmarks)")
    cols = [row[1] for row in cursor.fetchall()]
    if cols and "tags" not in cols:
        cursor.execute("ALTER TABLE bookmarks ADD COLUMN tags TEXT DEFAULT '[]'")
        cursor.execute("UPDATE bookmarks SET tags = '[]' WHERE tags IS NULL OR tags = ''")


def _migrate_favorite_column(conn: sqlite3.Connection) -> None:
    """Adds is_favorite column to bookmarks table if missing (backward compatibility)."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(bookmarks)")
    cols = [row[1] for row in cursor.fetchall()]
    if cols and "is_favorite" not in cols:
        cursor.execute("ALTER TABLE bookmarks ADD COLUMN is_favorite INTEGER DEFAULT 0")
        cursor.execute("UPDATE bookmarks SET is_favorite = 0 WHERE is_favorite IS NULL")


def _migrate_archived_column(conn: sqlite3.Connection) -> None:
    """Adds archived column to bookmarks table if missing (backward compatibility)."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(bookmarks)")
    cols = [row[1] for row in cursor.fetchall()]
    if cols and "archived" not in cols:
        cursor.execute("ALTER TABLE bookmarks ADD COLUMN archived INTEGER DEFAULT 0")
        cursor.execute("UPDATE bookmarks SET archived = 0 WHERE archived IS NULL")


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Migrates bookmarks schema ensuring notes, tags, is_favorite, and archived columns exist."""
    _migrate_notes_column(conn)
    _migrate_tags_column(conn)
    _migrate_favorite_column(conn)
    _migrate_archived_column(conn)


# Backward-compatible function aliases
migrate_notes_column = _migrate_notes_column
migrate_tags_column = _migrate_tags_column
_migrate_tags = _migrate_tags_column
migrate_favorite_column = _migrate_favorite_column
migrate_archived_column = _migrate_archived_column
_migrate_schema = migrate_schema


def normalize_tags(tags: Any) -> List[str]:
    """Normalizes and deduplicates tags, returning a list of non-empty strings."""
    if tags is None:
        return []
    if isinstance(tags, str):
        raw_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, (list, tuple, set)):
        raw_list = [str(t).strip() for t in tags if str(t).strip()]
    else:
        return []

    seen = set()
    deduped = []
    for t in raw_list:
        lower = t.lower()
        if lower not in seen:
            seen.add(lower)
            deduped.append(t)
    return deduped


def init_db(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    """
    Initializes the SQLite database at `db_path`, creating the bookmarks table
    with notes, tags, is_favorite, and archived columns and performing backward-compatible table migration
    adding columns via ALTER TABLE if missing.
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
                    tags TEXT DEFAULT '[]',
                    is_favorite INTEGER DEFAULT 0,
                    archived INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            _migrate_notes_column(conn)
            _migrate_tags_column(conn)
            _migrate_favorite_column(conn)
            _migrate_archived_column(conn)
    finally:
        conn.close()


def row_to_dict(row: Union[sqlite3.Row, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Converts a SQLite Row into a bookmark dictionary, ensuring
    'is_favorite' and 'archived' are returned as Python booleans, 'notes' as a string,
    and 'tags' as a list of strings.
    """
    is_fav = False
    try:
        is_fav = bool(row["is_favorite"])
    except (IndexError, KeyError):
        is_fav = False

    is_arch = False
    try:
        is_arch = bool(row["archived"])
    except (IndexError, KeyError):
        is_arch = False

    notes_str = ""
    try:
        raw_notes = row["notes"]
        notes_str = str(raw_notes) if raw_notes is not None else ""
    except (IndexError, KeyError):
        notes_str = ""

    tags_list: List[str] = []
    try:
        raw_tags = row["tags"]
        if raw_tags is not None:
            if isinstance(raw_tags, str):
                tags_list = json.loads(raw_tags) if raw_tags.strip() else []
            elif isinstance(raw_tags, (list, tuple)):
                tags_list = list(raw_tags)
        if not isinstance(tags_list, list):
            tags_list = []
    except (IndexError, KeyError, ValueError, TypeError):
        tags_list = []

    clean_tags = [str(t) for t in tags_list]

    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "notes": notes_str,
        "tags": clean_tags,
        "is_favorite": is_fav,
        "archived": is_arch,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# Private alias for row_to_dict
_row_to_dict = row_to_dict


def get_bookmarks(
    q: Optional[str] = None,
    favorites_only: Union[bool, str, Path] = False,
    tag: Optional[Union[str, Path]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    *,
    filter_tag: Optional[str] = None,
    archived: Optional[Union[bool, str]] = False,
) -> List[Dict[str, Any]]:
    """
    Retrieves all bookmarks, optionally filtered by search term `q` across
    title, url, notes, and tags (case-insensitive substring match),
    by `favorites_only` flag, by specific `tag`, and by `archived` status.
    Bookmarks are returned ordered by id ASC.
    """
    fav_filter = False
    if isinstance(favorites_only, bool):
        fav_filter = favorites_only
    elif isinstance(favorites_only, Path):
        db_path = favorites_only
        fav_filter = False
    elif isinstance(favorites_only, str):
        if favorites_only.lower() in ("true", "1"):
            fav_filter = True
        elif favorites_only.lower() in ("false", "0", ""):
            fav_filter = False
        elif "/" in favorites_only or "\\" in favorites_only or favorites_only.endswith(".db"):
            db_path = favorites_only
            fav_filter = False

    # Handle backward-compatible positional call where 3rd arg was db_path
    tag_filter: Optional[str] = None
    if filter_tag is not None:
        tag_filter = str(filter_tag).strip()
    elif tag is not None:
        if isinstance(tag, Path) or (isinstance(tag, str) and ("/" in tag or "\\" in tag or tag.endswith(".db"))):
            db_path = tag
            tag_filter = None
        else:
            tag_filter = str(tag).strip()

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        conditions: List[str] = []
        params: List[Any] = []

        if fav_filter:
            conditions.append("is_favorite = 1")

        # Archive filter handling
        if archived is not None:
            if isinstance(archived, bool):
                conditions.append("COALESCE(archived, 0) = ?")
                params.append(1 if archived else 0)
            elif isinstance(archived, int):
                conditions.append("COALESCE(archived, 0) = ?")
                params.append(1 if archived else 0)
            elif isinstance(archived, str):
                arch_lower = archived.strip().lower()
                if arch_lower in ("true", "1"):
                    conditions.append("COALESCE(archived, 0) = 1")
                elif arch_lower in ("all", "*"):
                    pass  # Include both archived and unarchived
                else:
                    # 'false', '0', empty, or unrecognized values default to
                    # active-only visibility per spec (default behavior).
                    conditions.append("COALESCE(archived, 0) = 0")

        if tag_filter:
            tag_lower = tag_filter.lower()
            conditions.append(
                "(EXISTS (SELECT 1 FROM json_each(bookmarks.tags) WHERE LOWER(json_each.value) = ?) OR "
                "instr(LOWER(COALESCE(tags, '[]')), LOWER(?)) > 0)"
            )
            params.extend([tag_lower, f'"{tag_lower}"'])

        if q is not None and str(q).strip() != "":
            query_str = str(q).strip().lower()
            conditions.append(
                "(instr(LOWER(COALESCE(title, '')), LOWER(?)) > 0 OR "
                "instr(LOWER(COALESCE(url, '')), LOWER(?)) > 0 OR "
                "instr(LOWER(COALESCE(notes, '')), LOWER(?)) > 0 OR "
                "instr(LOWER(COALESCE(tags, '[]')), LOWER(?)) > 0)"
            )
            params.extend([query_str, query_str, query_str, query_str])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT id, title, url, notes, tags, is_favorite, archived, created_at, updated_at
            FROM bookmarks
            {where_clause}
            ORDER BY id ASC
        """
        try:
            cursor.execute(sql, params)
        except sqlite3.OperationalError as e:
            err_msg = str(e)
            if any(col in err_msg for col in ("is_favorite", "notes", "tags", "archived")):
                with conn:
                    _migrate_notes_column(conn)
                    _migrate_tags_column(conn)
                    _migrate_favorite_column(conn)
                    _migrate_archived_column(conn)
                cursor.execute(sql, params)
            else:
                raise

        rows = cursor.fetchall()
        return [row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_all_bookmarks(
    q: Optional[str] = None,
    favorites_only: Union[bool, str, Path] = False,
    tag: Optional[Union[str, Path]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    *,
    archived: Optional[Union[bool, str]] = False,
) -> List[Dict[str, Any]]:
    """
    Retrieves all bookmarks, supporting optional search term `q`,
    `favorites_only` filter, `tag` filter, and `archived` filter. Alias for get_bookmarks.
    """
    return get_bookmarks(q=q, favorites_only=favorites_only, tag=tag, db_path=db_path, archived=archived)


def get_all_tags(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> List[str]:
    """Retrieves all distinct tags across all bookmarks, sorted alphabetically."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT DISTINCT json_each.value
                FROM bookmarks, json_each(bookmarks.tags)
                WHERE json_each.value IS NOT NULL AND trim(json_each.value) != ''
                ORDER BY LOWER(json_each.value) ASC
            """)
            return [str(row[0]) for row in cursor.fetchall()]
        except sqlite3.OperationalError as e:
            if "no such column: tags" in str(e) or "no such table" in str(e):
                return []
            try:
                cursor.execute("SELECT tags FROM bookmarks WHERE tags IS NOT NULL AND tags != ''")
                all_tags = set()
                for (raw,) in cursor.fetchall():
                    for t in normalize_tags(raw):
                        all_tags.add(t)
                return sorted(list(all_tags), key=lambda x: x.lower())
            except Exception:
                return []
    finally:
        conn.close()


def get_bookmark_by_id(
    id: Optional[Union[int, str]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    *,
    bookmark_id: Optional[Union[int, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single bookmark by ID, or None if not found."""
    raw_id = id if id is not None else bookmark_id
    if raw_id is None:
        return None

    try:
        target_id = int(raw_id)
        if target_id <= 0:
            return None
    except (ValueError, TypeError):
        return None

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        sql = """
            SELECT id, title, url, notes, tags, is_favorite, archived, created_at, updated_at
            FROM bookmarks
            WHERE id = ?
        """
        try:
            cursor.execute(sql, (target_id,))
        except sqlite3.OperationalError as e:
            err_msg = str(e)
            if any(col in err_msg for col in ("is_favorite", "notes", "tags", "archived")):
                with conn:
                    _migrate_notes_column(conn)
                    _migrate_tags_column(conn)
                    _migrate_favorite_column(conn)
                    _migrate_archived_column(conn)
                cursor.execute(sql, (target_id,))
            else:
                raise

        row = cursor.fetchone()
        if row is None:
            return None
        return row_to_dict(row)
    finally:
        conn.close()


def create_bookmark(
    title: str,
    url: str,
    notes: Optional[Union[str, bool]] = "",
    is_favorite: Union[bool, int, str, Path] = False,
    tags: Optional[Union[List[str], str, Path]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    *,
    archived: Union[bool, int, str] = False,
) -> Dict[str, Any]:
    """
    Creates a new bookmark with title, url, optional notes, optional is_favorite flag,
    optional tags list, and optional archived flag.
    Sets created_at and updated_at to the current UTC timestamp.
    """
    clean_title = title.strip() if isinstance(title, str) else title
    clean_url = url.strip() if isinstance(url, str) else url
    now_iso = get_utc_now()

    # Handle backward-compatible positional call where 3rd arg was is_favorite
    fav_bool = False
    if isinstance(notes, bool):
        fav_bool = notes
        notes_val = ""
        if isinstance(is_favorite, (str, Path)) and (
            isinstance(is_favorite, Path)
            or "/" in str(is_favorite)
            or "\\" in str(is_favorite)
            or str(is_favorite).endswith(".db")
        ):
            db_path = is_favorite
    else:
        notes_val = str(notes) if notes is not None else ""
        if isinstance(is_favorite, bool):
            fav_bool = is_favorite
        elif isinstance(is_favorite, Path):
            db_path = is_favorite
            fav_bool = False
        elif isinstance(is_favorite, str):
            if is_favorite.lower() in ("true", "1"):
                fav_bool = True
            elif is_favorite.lower() in ("false", "0", ""):
                fav_bool = False
            elif "/" in is_favorite or "\\" in is_favorite or is_favorite.endswith(".db"):
                db_path = is_favorite
                fav_bool = False
        elif isinstance(is_favorite, int):
            fav_bool = bool(is_favorite)

    fav_int = 1 if fav_bool else 0

    # Handle archived flag
    arch_bool = False
    if isinstance(archived, bool):
        arch_bool = archived
    elif isinstance(archived, str):
        arch_bool = archived.lower() in ("true", "1")
    elif isinstance(archived, int):
        arch_bool = bool(archived)
    arch_int = 1 if arch_bool else 0

    # Handle backward-compatible positional call where 5th arg was db_path
    tags_arg: List[str] = []
    if isinstance(tags, Path) or (isinstance(tags, str) and ("/" in tags or "\\" in tags or tags.endswith(".db"))):
        db_path = tags
        tags_arg = []
    elif tags is not None:
        tags_arg = normalize_tags(tags)

    tags_json = json.dumps(tags_arg)

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO bookmarks (title, url, notes, tags, is_favorite, archived, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (clean_title, clean_url, notes_val, tags_json, fav_int, arch_int, now_iso, now_iso),
                )
            except sqlite3.OperationalError as e:
                err_msg = str(e)
                if any(col in err_msg for col in ("is_favorite", "notes", "tags", "archived")):
                    _migrate_notes_column(conn)
                    _migrate_tags_column(conn)
                    _migrate_favorite_column(conn)
                    _migrate_archived_column(conn)
                    cursor.execute(
                        """
                        INSERT INTO bookmarks (title, url, notes, tags, is_favorite, archived, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (clean_title, clean_url, notes_val, tags_json, fav_int, arch_int, now_iso, now_iso),
                    )
                else:
                    raise
            created_id = cursor.lastrowid

        return {
            "id": created_id,
            "title": clean_title,
            "url": clean_url,
            "notes": notes_val,
            "tags": tags_arg,
            "is_favorite": fav_bool,
            "archived": arch_bool,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    finally:
        conn.close()


def update_bookmark(
    id: Optional[Union[int, str]] = None,
    title: Optional[str] = None,
    url: Optional[str] = None,
    notes: Optional[str] = None,
    is_favorite: Optional[Union[bool, int, str, Path]] = None,
    tags: Optional[Union[List[str], str]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    *,
    bookmark_id: Optional[Union[int, str]] = None,
    archived: Optional[Union[bool, int, str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Updates an existing bookmark's title, url, notes, tags, is_favorite, and/or archived status.
    Updates the updated_at timestamp to current UTC time.
    Returns the complete updated bookmark record, or None if not found.
    """
    raw_id = id if id is not None else bookmark_id
    if raw_id is None:
        return None

    try:
        target_id = int(raw_id)
        if target_id <= 0:
            return None
    except (ValueError, TypeError):
        return None

    # Handle backward-compatible positional call where 4th arg was is_favorite
    fav_val: Optional[int] = None
    if isinstance(notes, bool):
        fav_val = 1 if notes else 0
        notes = None
        if isinstance(is_favorite, (str, Path)) and (
            isinstance(is_favorite, Path)
            or "/" in str(is_favorite)
            or "\\" in str(is_favorite)
            or str(is_favorite).endswith(".db")
        ):
            db_path = is_favorite
    elif isinstance(is_favorite, bool):
        fav_val = 1 if is_favorite else 0
    elif isinstance(is_favorite, Path):
        db_path = is_favorite
        fav_val = None
    elif isinstance(is_favorite, str):
        if is_favorite.lower() in ("true", "1"):
            fav_val = 1
        elif is_favorite.lower() in ("false", "0"):
            fav_val = 0
        elif "/" in is_favorite or "\\" in is_favorite or is_favorite.endswith(".db"):
            db_path = is_favorite
            fav_val = None
    elif isinstance(is_favorite, int):
        fav_val = 1 if is_favorite else 0

    arch_val: Optional[int] = None
    if archived is not None:
        if isinstance(archived, bool):
            arch_val = 1 if archived else 0
        elif isinstance(archived, str):
            arch_val = 1 if archived.lower() in ("true", "1") else 0
        elif isinstance(archived, int):
            arch_val = 1 if archived else 0

    existing = get_bookmark_by_id(target_id, db_path=db_path)
    if existing is None:
        return None

    updates: List[str] = []
    params: List[Any] = []

    if title is not None:
        clean_title = title.strip() if isinstance(title, str) else title
        updates.append("title = ?")
        params.append(clean_title)
    if url is not None:
        clean_url = url.strip() if isinstance(url, str) else url
        updates.append("url = ?")
        params.append(clean_url)
    if notes is not None:
        updates.append("notes = ?")
        params.append(str(notes))
    if fav_val is not None:
        updates.append("is_favorite = ?")
        params.append(fav_val)
    if arch_val is not None:
        updates.append("archived = ?")
        params.append(arch_val)
    if tags is not None:
        norm_tags = normalize_tags(tags)
        updates.append("tags = ?")
        params.append(json.dumps(norm_tags))

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
            try:
                cursor.execute(
                    f"UPDATE bookmarks SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
            except sqlite3.OperationalError as e:
                err_msg = str(e)
                if any(col in err_msg for col in ("is_favorite", "notes", "tags", "archived")):
                    _migrate_notes_column(conn)
                    _migrate_tags_column(conn)
                    _migrate_favorite_column(conn)
                    _migrate_archived_column(conn)
                    cursor.execute(
                        f"UPDATE bookmarks SET {', '.join(updates)} WHERE id = ?",
                        params,
                    )
                else:
                    raise

            try:
                cursor.execute(
                    """
                    SELECT id, title, url, notes, tags, is_favorite, archived, created_at, updated_at
                    FROM bookmarks
                    WHERE id = ?
                    """,
                    (target_id,),
                )
            except sqlite3.OperationalError as e:
                err_msg = str(e)
                if any(col in err_msg for col in ("is_favorite", "notes", "tags", "archived")):
                    _migrate_notes_column(conn)
                    _migrate_tags_column(conn)
                    _migrate_favorite_column(conn)
                    _migrate_archived_column(conn)
                    cursor.execute(
                        """
                        SELECT id, title, url, notes, tags, is_favorite, archived, created_at, updated_at
                        FROM bookmarks
                        WHERE id = ?
                        """,
                        (target_id,),
                    )
                else:
                    raise

            row = cursor.fetchone()
            if row is None:
                return None
            return row_to_dict(row)
    finally:
        conn.close()


def archive_bookmark(
    id: Union[int, str],
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Marks a bookmark as archived (archived = 1)."""
    return update_bookmark(id=id, archived=True, db_path=db_path)


def restore_bookmark(
    id: Union[int, str],
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Restores an archived bookmark (archived = 0)."""
    return update_bookmark(id=id, archived=False, db_path=db_path)


def delete_bookmark(
    id: Optional[Union[int, str]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    *,
    bookmark_id: Optional[Union[int, str]] = None,
) -> bool:
    """Deletes a bookmark by ID. Returns True if deleted, False if not found."""
    raw_id = id if id is not None else bookmark_id
    if raw_id is None:
        return False

    try:
        target_id = int(raw_id)
        if target_id <= 0:
            return False
    except (ValueError, TypeError):
        return False

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bookmarks WHERE id = ?", (target_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()
