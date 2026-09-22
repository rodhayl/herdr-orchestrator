"""
MiniLinks SQLite Database Persistence Test Suite.

Validates that bookmarks, updates, and deletions survive server restarts across ephemeral ports,
and verifies database schema and integrity directly using the sqlite3 module.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Ensure examples/minilinks and repository root are on sys.path
_current_file = Path(__file__).resolve()
_minilinks_dir = _current_file.parent.parent if _current_file.parent.name in ("tests", "scripts") else _current_file.parent
_repo_root = _minilinks_dir.parent.parent if _minilinks_dir.name == "minilinks" else _minilinks_dir.parent

for _p in (str(_minilinks_dir), str(_repo_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from app.server import create_server
except ImportError:
    try:
        from examples.minilinks.app.server import create_server
    except ImportError as _err:
        raise ImportError(
            "Could not import 'create_server' from 'app.server' or 'examples.minilinks.app.server'. "
            f"sys.path={sys.path}"
        ) from _err


def _http_request_json(base_url: str, method: str, path: str, data=None):
    """Helper to send HTTP request and decode JSON response."""
    url = f"{base_url}{path}"
    headers = {}
    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp_body = resp.read()
            return resp.status, json.loads(resp_body.decode("utf-8")) if resp_body else None
    except urllib.error.HTTPError as err:
        err_body = err.read()
        return err.code, json.loads(err_body.decode("utf-8")) if err_body else None


class TestDatabasePersistence(unittest.TestCase):
    """Verifies SQLite persistence across server lifecycle restarts and direct SQLite queries."""

    def test_persistence_across_server_restart(self):
        """
        Validates the complete 7-step persistence scenario from SPEC.md 7.1.2:
        1. Start Server 1 on an ephemeral port with a temporary db_path.
        2. Insert bookmarks into Server 1 via POST /api/bookmarks, and update one.
        3. Shut down Server 1 cleanly (shutdown, server_close).
        4. Verify database file integrity directly using sqlite3 module.
        5. Start Server 2 pointing to the same db_path on a new ephemeral port.
        6. Verify all previously created bookmarks, updated notes, and timestamps persist.
        7. Shut down Server 2 cleanly and clean up temporary database files.
        """
        temp_dir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(temp_dir.name, "persistence_test.db")

            # 1. Start Server 1 on ephemeral port
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port1 = getattr(server1, "server_port", None) or server1.server_address[1]
            base_url1 = f"http://127.0.0.1:{port1}"

            # 2. Insert bookmarks into Server 1
            payload1 = {
                "title": "Python Documentation",
                "url": "https://docs.python.org/3/",
                "notes": "Official reference guide",
            }
            status1, bm1 = _http_request_json(base_url1, "POST", "/api/bookmarks", data=payload1)
            self.assertEqual(status1, 201)
            self.assertIsInstance(bm1.get("id"), int)
            id1 = bm1["id"]
            created_at1 = bm1["created_at"]

            payload2 = {
                "title": "SQLite Tutorial",
                "url": "https://www.sqlite.org/",
                "notes": "Lightweight database engine",
            }
            status2, bm2 = _http_request_json(base_url1, "POST", "/api/bookmarks", data=payload2)
            self.assertEqual(status2, 201)
            id2 = bm2["id"]

            # Update Bookmark 1 notes
            time.sleep(0.05)
            status_patch, updated_bm1 = _http_request_json(
                base_url1, "PATCH", f"/api/bookmarks/{id1}", data={"notes": "Updated reference notes"}
            )
            self.assertEqual(status_patch, 200)
            self.assertEqual(updated_bm1["notes"], "Updated reference notes")
            updated_at1 = updated_bm1["updated_at"]

            # 3. Cleanly shut down Server 1
            server1.shutdown()
            server1.server_close()

            # 4. Verify database file directly with sqlite3
            self.assertTrue(os.path.exists(db_path), f"Database file missing at {db_path}")
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()

                # Verify PRAGMA integrity_check
                cursor.execute("PRAGMA integrity_check;")
                integrity_result = cursor.fetchone()
                self.assertIsNotNone(integrity_result)
                self.assertEqual(integrity_result[0], "ok")

                # Verify bookmarks table rows
                cursor.execute("SELECT id, title, url, notes, created_at, updated_at FROM bookmarks ORDER BY id ASC;")
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 2)

                # Row 1 check
                r1_id, r1_title, r1_url, r1_notes, r1_created_at, r1_updated_at = rows[0]
                self.assertEqual(r1_id, id1)
                self.assertEqual(r1_title, "Python Documentation")
                self.assertEqual(r1_url, "https://docs.python.org/3/")
                self.assertEqual(r1_notes, "Updated reference notes")
                self.assertEqual(r1_created_at, created_at1)
                self.assertEqual(r1_updated_at, updated_at1)

                # Row 2 check
                r2_id, r2_title, r2_url, r2_notes, _, _ = rows[1]
                self.assertEqual(r2_id, id2)
                self.assertEqual(r2_title, "SQLite Tutorial")
                self.assertEqual(r2_url, "https://www.sqlite.org/")
                self.assertEqual(r2_notes, "Lightweight database engine")
            finally:
                conn.close()

            # 5. Start Server 2 on a new ephemeral port pointing to same db_path
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port2 = getattr(server2, "server_port", None) or server2.server_address[1]
            base_url2 = f"http://127.0.0.1:{port2}"

            try:
                # 6. Verify all previously created bookmarks and updated notes persist via Server 2
                status_get, all_bms = _http_request_json(base_url2, "GET", "/api/bookmarks")
                self.assertEqual(status_get, 200)
                self.assertEqual(len(all_bms), 2)

                # Check Bookmark 1 persisted fields
                saved_bm1 = next((b for b in all_bms if b["id"] == id1), None)
                self.assertIsNotNone(saved_bm1)
                self.assertEqual(saved_bm1["title"], "Python Documentation")
                self.assertEqual(saved_bm1["url"], "https://docs.python.org/3/")
                self.assertEqual(saved_bm1["notes"], "Updated reference notes")
                self.assertEqual(saved_bm1["created_at"], created_at1)
                self.assertEqual(saved_bm1["updated_at"], updated_at1)

                # Check Bookmark 2 persisted fields
                saved_bm2 = next((b for b in all_bms if b["id"] == id2), None)
                self.assertIsNotNone(saved_bm2)
                self.assertEqual(saved_bm2["title"], "SQLite Tutorial")
                self.assertEqual(saved_bm2["url"], "https://www.sqlite.org/")
                self.assertEqual(saved_bm2["notes"], "Lightweight database engine")

                # Verify query filtering works on persisted data
                status_q, search_results = _http_request_json(base_url2, "GET", "/api/bookmarks?q=Updated")
                self.assertEqual(status_q, 200)
                self.assertEqual(len(search_results), 1)
                self.assertEqual(search_results[0]["id"], id1)

                # Verify that inserting a new bookmark on Server 2 increments id correctly
                payload3 = {
                    "title": "MDN Web Docs",
                    "url": "https://developer.mozilla.org/",
                    "notes": "Web standards and APIs",
                }
                status3, bm3 = _http_request_json(base_url2, "POST", "/api/bookmarks", data=payload3)
                self.assertEqual(status3, 201)
                self.assertGreater(bm3["id"], id2)

                # Verify listing now has 3 bookmarks
                status_all, updated_list = _http_request_json(base_url2, "GET", "/api/bookmarks")
                self.assertEqual(status_all, 200)
                self.assertEqual(len(updated_list), 3)

            finally:
                # 7. Cleanly shut down Server 2
                server2.shutdown()
                server2.server_close()

        finally:
            temp_dir.cleanup()

    def test_deletion_persistence_across_restart(self):
        """Validates that bookmark deletions persist across server restarts."""
        temp_dir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(temp_dir.name, "deletion_test.db")

            # Start Server 1
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port1 = getattr(server1, "server_port", None) or server1.server_address[1]
            base_url1 = f"http://127.0.0.1:{port1}"

            # Create two bookmarks
            _, bm1 = _http_request_json(base_url1, "POST", "/api/bookmarks", data={"title": "Keep", "url": "https://keep.org"})
            _, bm2 = _http_request_json(base_url1, "POST", "/api/bookmarks", data={"title": "Delete", "url": "https://delete.org"})

            # Delete bookmark 2
            del_status, del_resp = _http_request_json(base_url1, "DELETE", f"/api/bookmarks/{bm2['id']}")
            self.assertEqual(del_status, 200)
            self.assertEqual(del_resp.get("status"), "deleted")

            # Shut down Server 1
            server1.shutdown()
            server1.server_close()

            # Start Server 2 on new port
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port2 = getattr(server2, "server_port", None) or server2.server_address[1]
            base_url2 = f"http://127.0.0.1:{port2}"

            try:
                # GET bookmarks on Server 2
                status, bms = _http_request_json(base_url2, "GET", "/api/bookmarks")
                self.assertEqual(status, 200)
                self.assertEqual(len(bms), 1)
                self.assertEqual(bms[0]["id"], bm1["id"])
                self.assertEqual(bms[0]["title"], "Keep")

                # Deleting bm2 again should return 404
                status_del2, _ = _http_request_json(base_url2, "DELETE", f"/api/bookmarks/{bm2['id']}")
                self.assertEqual(status_del2, 404)
            finally:
                server2.shutdown()
                server2.server_close()

        finally:
            temp_dir.cleanup()

    def test_sqlite_schema_definition(self):
        """Verifies the table schema, column definitions, and NOT NULL constraints in SQLite."""
        temp_dir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(temp_dir.name, "schema_test.db")
            server = create_server(host="127.0.0.1", port=0, db_path=db_path)
            server.shutdown()
            server.server_close()

            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(bookmarks);")
                columns = {row[1]: {"type": row[2].upper(), "notnull": row[3], "dflt_value": row[4], "pk": row[5]} for row in cursor.fetchall()}

                # Columns specified in SPEC.md 2.2
                self.assertIn("id", columns)
                self.assertTrue(columns["id"]["pk"] >= 1)

                self.assertIn("title", columns)
                self.assertEqual(columns["title"]["type"], "TEXT")
                self.assertEqual(columns["title"]["notnull"], 1)

                self.assertIn("url", columns)
                self.assertEqual(columns["url"]["type"], "TEXT")
                self.assertEqual(columns["url"]["notnull"], 1)

                self.assertIn("notes", columns)
                self.assertEqual(columns["notes"]["type"], "TEXT")

                self.assertIn("created_at", columns)
                self.assertEqual(columns["created_at"]["type"], "TEXT")
                self.assertEqual(columns["created_at"]["notnull"], 1)

                self.assertIn("updated_at", columns)
                self.assertEqual(columns["updated_at"]["type"], "TEXT")
                self.assertEqual(columns["updated_at"]["notnull"], 1)

                # Verify integrity constraint prevents inserting NULL title
                with self.assertRaises(sqlite3.IntegrityError):
                    cursor.execute(
                        "INSERT INTO bookmarks (title, url, created_at, updated_at) VALUES (NULL, 'https://test.com', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');"
                    )
                    conn.commit()

                # Verify integrity constraint prevents inserting NULL url
                with self.assertRaises(sqlite3.IntegrityError):
                    cursor.execute(
                        "INSERT INTO bookmarks (title, url, created_at, updated_at) VALUES ('Title', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');"
                    )
                    conn.commit()

            finally:
                conn.close()

        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
