"""
tests/test_persistence.py
Validates SQLite persistence across server lifecycle restarts using standard library
unittest, tempfile, sqlite3, urllib, and threading.
"""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from typing import Any, Optional, Tuple

# Ensure repository root is on sys.path for direct imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.server import create_server


def make_http_request(
    base_url: str,
    method: str,
    path: str,
    payload: Optional[dict] = None,
) -> Tuple[int, Any, dict]:
    """Helper function to perform an HTTP request using urllib.request."""
    url = f"{base_url}{path}"
    headers = {}
    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read()
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:
                parsed = body.decode("utf-8", errors="replace")
            return resp.status, parsed, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = body.decode("utf-8", errors="replace")
        return e.code, parsed, dict(e.headers)


class TestPersistence(unittest.TestCase):
    """Verifies SQLite persistence integrity across server restarts and crashes."""

    def test_persistence_across_server_restart(self):
        """
        Validates SQLite persistence across server lifecycle restarts:
        1. Starts Server 1 on ephemeral port with db_path=temp_db.db.
        2. Inserts tasks into Server 1 via POST /api/tasks and updates one.
        3. Shuts down Server 1 (shutdown(), server_close()).
        4. Verifies database file integrity directly via sqlite3 standard library module.
        5. Starts Server 2 pointing to the same db_path on a new ephemeral port.
        6. Verifies all previously created tasks and updated statuses are intact via GET /api/tasks.
        7. Modifies data on Server 2 (delete and create) and shuts down cleanly.
        """
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "persistence_restart.db")

        try:
            # 1. Start Server 1 on ephemeral port
            server1, thread1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base_url1 = f"http://127.0.0.1:{server1.server_port}"

            try:
                # 2. Insert tasks into Server 1
                status, task1, _ = make_http_request(
                    base_url1, "POST", "/api/tasks", {"title": "Task 1", "status": "TODO"}
                )
                self.assertEqual(status, 201)
                task1_id = task1["id"]

                status, task2, _ = make_http_request(
                    base_url1, "POST", "/api/tasks", {"title": "Task 2", "status": "DOING"}
                )
                self.assertEqual(status, 201)
                task2_id = task2["id"]

                status, task3, _ = make_http_request(
                    base_url1, "POST", "/api/tasks", {"title": "Task 3", "status": "DONE"}
                )
                self.assertEqual(status, 201)
                task3_id = task3["id"]

                # Update Task 1 status to DOING and title to "Task 1 Updated"
                status, updated_task1, _ = make_http_request(
                    base_url1,
                    "PATCH",
                    f"/api/tasks/{task1_id}",
                    {"title": "Task 1 Updated", "status": "DOING"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(updated_task1["title"], "Task 1 Updated")
                self.assertEqual(updated_task1["status"], "DOING")

            finally:
                # 3. Cleanly shut down Server 1
                server1.shutdown()
                server1.server_close()
                thread1.join(timeout=5.0)

            # 4. Verify database file integrity directly via sqlite3
            self.assertTrue(os.path.exists(db_path), "Database file must exist on disk after shutdown")

            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchall()
                self.assertEqual(integrity, [("ok",)], "SQLite database integrity check must pass")

                cursor.execute(
                    "SELECT id, title, status, created_at, updated_at FROM tasks ORDER BY id ASC"
                )
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 3, "Database must contain exactly 3 tasks")

                # Verify task 1
                self.assertEqual(rows[0][0], task1_id)
                self.assertEqual(rows[0][1], "Task 1 Updated")
                self.assertEqual(rows[0][2], "DOING")

                # Verify task 2
                self.assertEqual(rows[1][0], task2_id)
                self.assertEqual(rows[1][1], "Task 2")
                self.assertEqual(rows[1][2], "DOING")

                # Verify task 3
                self.assertEqual(rows[2][0], task3_id)
                self.assertEqual(rows[2][1], "Task 3")
                self.assertEqual(rows[2][2], "DONE")
            finally:
                conn.close()

            # 5. Start Server 2 pointing to the same db_path on a new ephemeral port
            server2, thread2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base_url2 = f"http://127.0.0.1:{server2.server_port}"

            try:
                # 6. Verify all tasks and their updated statuses via GET /api/tasks on Server 2
                status, tasks, _ = make_http_request(base_url2, "GET", "/api/tasks")
                self.assertEqual(status, 200)
                self.assertIsInstance(tasks, list)
                self.assertEqual(len(tasks), 3)

                t1 = next(t for t in tasks if t["id"] == task1_id)
                self.assertEqual(t1["title"], "Task 1 Updated")
                self.assertEqual(t1["status"], "DOING")

                t2 = next(t for t in tasks if t["id"] == task2_id)
                self.assertEqual(t2["title"], "Task 2")
                self.assertEqual(t2["status"], "DOING")

                t3 = next(t for t in tasks if t["id"] == task3_id)
                self.assertEqual(t3["title"], "Task 3")
                self.assertEqual(t3["status"], "DONE")

                # 7. Modify data on Server 2: delete Task 2, create Task 4
                status, del_resp, _ = make_http_request(
                    base_url2, "DELETE", f"/api/tasks/{task2_id}"
                )
                self.assertEqual(status, 200)
                self.assertEqual(del_resp.get("status"), "deleted")

                status, task4, _ = make_http_request(
                    base_url2, "POST", "/api/tasks", {"title": "Task 4 Post Restart"}
                )
                self.assertEqual(status, 201)
                task4_id = task4["id"]

                # Re-query Server 2 to verify current state
                status, final_tasks, _ = make_http_request(base_url2, "GET", "/api/tasks")
                self.assertEqual(status, 200)
                final_ids = [t["id"] for t in final_tasks]
                self.assertIn(task1_id, final_ids)
                self.assertNotIn(task2_id, final_ids)
                self.assertIn(task3_id, final_ids)
                self.assertIn(task4_id, final_ids)

            finally:
                # Cleanly shut down Server 2
                server2.shutdown()
                server2.server_close()
                thread2.join(timeout=5.0)

            # Final direct SQLite check after Server 2 shutdown
            conn2 = sqlite3.connect(db_path)
            try:
                cursor = conn2.cursor()
                cursor.execute("SELECT id FROM tasks ORDER BY id ASC")
                db_ids = [r[0] for r in cursor.fetchall()]
                self.assertEqual(db_ids, [task1_id, task3_id, task4_id])
            finally:
                conn2.close()

        finally:
            temp_dir.cleanup()

    def test_sqlite_schema_and_constraints(self):
        """
        Verifies that SQLite schema conforms strictly to specification:
        - Table 'tasks' with columns: id, title, status, created_at, updated_at
        - Status column check constraint strictly allows only 'TODO', 'DOING', 'DONE'
        - Title column cannot be NULL
        """
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "schema_test.db")

        try:
            # Start server to trigger database initialization and schema creation
            server, thread = create_server(host="127.0.0.1", port=0, db_path=db_path)
            try:
                pass
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5.0)

            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()

                # Verify table exists
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
                )
                self.assertIsNotNone(cursor.fetchone(), "Table 'tasks' must exist")

                # Verify column definitions
                cursor.execute("PRAGMA table_info(tasks)")
                columns = {col[1]: {"type": col[2], "notnull": col[3], "pk": col[5]} for col in cursor.fetchall()}
                self.assertIn("id", columns)
                self.assertIn("title", columns)
                self.assertIn("status", columns)
                self.assertIn("created_at", columns)
                self.assertIn("updated_at", columns)

                self.assertEqual(columns["id"]["pk"], 1, "Column 'id' must be primary key")
                self.assertEqual(columns["title"]["notnull"], 1, "Column 'title' must be NOT NULL")
                self.assertEqual(columns["status"]["notnull"], 1, "Column 'status' must be NOT NULL")

                # Verify CHECK constraint at SQLite storage layer
                # Inserting invalid status must raise sqlite3.IntegrityError
                with self.assertRaises(sqlite3.IntegrityError):
                    cursor.execute(
                        "INSERT INTO tasks (title, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        ("Test", "INVALID_STATUS", "2026-09-23T00:00:00Z", "2026-09-23T00:00:00Z"),
                    )
                    conn.commit()

                # Inserting NULL title must raise sqlite3.IntegrityError
                with self.assertRaises(sqlite3.IntegrityError):
                    cursor.execute(
                        "INSERT INTO tasks (title, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (None, "TODO", "2026-09-23T00:00:00Z", "2026-09-23T00:00:00Z"),
                    )
                    conn.commit()

                # Inserting valid statuses must succeed
                for valid_status in ("TODO", "DOING", "DONE"):
                    cursor.execute(
                        "INSERT INTO tasks (title, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (f"Valid {valid_status}", valid_status, "2026-09-23T00:00:00Z", "2026-09-23T00:00:00Z"),
                    )
                conn.commit()

                cursor.execute("SELECT COUNT(*) FROM tasks")
                count = cursor.fetchone()[0]
                self.assertEqual(count, 3)

            finally:
                conn.close()
        finally:
            temp_dir.cleanup()

    def test_persistence_across_multiple_server_cycles(self):
        """Validates persistence across three consecutive server restarts."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "multi_cycle.db")

        try:
            # Cycle 1: Create initial task
            s1, t1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            try:
                status, task, _ = make_http_request(
                    f"http://127.0.0.1:{s1.server_port}",
                    "POST",
                    "/api/tasks",
                    {"title": "Cycle 1 Task"},
                )
                self.assertEqual(status, 201)
                task_id = task["id"]
            finally:
                s1.shutdown()
                s1.server_close()
                t1.join(timeout=5.0)

            # Cycle 2: Read task, update status to DOING
            s2, t2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            try:
                url2 = f"http://127.0.0.1:{s2.server_port}"
                status, tasks, _ = make_http_request(url2, "GET", "/api/tasks")
                self.assertEqual(status, 200)
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["title"], "Cycle 1 Task")

                status, _, _ = make_http_request(
                    url2, "PATCH", f"/api/tasks/{task_id}", {"status": "DOING"}
                )
                self.assertEqual(status, 200)
            finally:
                s2.shutdown()
                s2.server_close()
                t2.join(timeout=5.0)

            # Cycle 3: Read task, verify status is DOING, then transition to DONE
            s3, t3 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            try:
                url3 = f"http://127.0.0.1:{s3.server_port}"
                status, tasks, _ = make_http_request(url3, "GET", "/api/tasks")
                self.assertEqual(status, 200)
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["status"], "DOING")

                status, updated, _ = make_http_request(
                    url3, "PATCH", f"/api/tasks/{task_id}", {"status": "DONE"}
                )
                self.assertEqual(status, 200)
                self.assertEqual(updated["status"], "DONE")
            finally:
                s3.shutdown()
                s3.server_close()
                t3.join(timeout=5.0)

        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
