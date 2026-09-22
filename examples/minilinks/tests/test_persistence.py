"""Unit and integration test suite validating SQLite persistence across server restarts."""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Ensure examples/minilinks is in sys.path for direct imports
_current_dir = Path(__file__).resolve().parent
_minilinks_dir = _current_dir.parent
if str(_minilinks_dir) not in sys.path:
    sys.path.insert(0, str(_minilinks_dir))

from app import database
from app.server import MiniLinksServer, create_server


def send_http_request(
    base_url: str,
    method: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any]:
    """Sends an HTTP request and returns (status_code, parsed_json_response)."""
    headers = {}
    encoded_data = None
    if data is not None:
        encoded_data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    url = f"{base_url}{path}"
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read()

    parsed = None
    if body:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = None
    return status, parsed


class TestMiniLinksPersistence(unittest.TestCase):
    """Verifies SQLite persistence across server lifecycle restarts and direct DB inspection."""

    def test_persistence_across_server_restart(self) -> None:
        """
        Validates SQLite persistence across server lifecycle restarts:
        1. Starts Server 1 on an ephemeral port with a temporary db_path.
        2. Inserts bookmarks into Server 1 via POST /api/bookmarks.
        3. Shuts down Server 1 cleanly.
        4. Verifies database file integrity directly using the sqlite3 module.
        5. Starts Server 2 pointing to the same db_path on a new ephemeral port.
        6. Verifies all previously created bookmarks, updated notes, and timestamps persist.
        7. Shuts down Server 2 and cleans up temporary database files.
        """
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "persistence_restart.db")
        server1: Optional[MiniLinksServer] = None
        server2: Optional[MiniLinksServer] = None

        try:
            # 1. Start Server 1 on an ephemeral port
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port1 = server1.server_port
            base1 = f"http://127.0.0.1:{port1}"

            # 2. Insert bookmarks into Server 1
            bm1_payload = {
                "title": "Python Standard Library",
                "url": "https://docs.python.org/3/library/",
                "notes": "Essential standard library docs",
            }
            status1, created1 = send_http_request(
                base1, "POST", "/api/bookmarks", data=bm1_payload
            )
            self.assertEqual(status1, 201)
            bm1_id = created1["id"]
            bm1_created_at = created1["created_at"]
            bm1_orig_updated_at = created1["updated_at"]

            bm2_payload = {
                "title": "SQLite Official Site",
                "url": "https://www.sqlite.org/",
                "notes": "Self-contained SQL engine",
            }
            status2, created2 = send_http_request(
                base1, "POST", "/api/bookmarks", data=bm2_payload
            )
            self.assertEqual(status2, 201)
            bm2_id = created2["id"]
            bm2_created_at = created2["created_at"]
            bm2_updated_at = created2["updated_at"]

            # Sleep briefly to ensure updated_at changes across second boundary
            time.sleep(1.05)

            # Update Bookmark 1 via PATCH
            patch_payload = {"notes": "Updated standard library docs"}
            patch_status, patch_res = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{bm1_id}", data=patch_payload
            )
            self.assertEqual(patch_status, 200)
            bm1_new_updated_at = patch_res["updated_at"]
            self.assertNotEqual(bm1_orig_updated_at, bm1_new_updated_at)

            # 3. Clean shutdown of Server 1
            server1.shutdown()
            server1.server_close()
            server1 = None

            # 4. Verify database file integrity directly using sqlite3
            self.assertTrue(os.path.exists(db_path))
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, title, url, notes, created_at, updated_at
                    FROM bookmarks
                    ORDER BY id ASC
                    """
                )
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 2)

                # Validate row 1
                self.assertEqual(rows[0]["id"], bm1_id)
                self.assertEqual(rows[0]["title"], "Python Standard Library")
                self.assertEqual(rows[0]["url"], "https://docs.python.org/3/library/")
                self.assertEqual(rows[0]["notes"], "Updated standard library docs")
                self.assertEqual(rows[0]["created_at"], bm1_created_at)
                self.assertEqual(rows[0]["updated_at"], bm1_new_updated_at)

                # Validate row 2
                self.assertEqual(rows[1]["id"], bm2_id)
                self.assertEqual(rows[1]["title"], "SQLite Official Site")
                self.assertEqual(rows[1]["url"], "https://www.sqlite.org/")
                self.assertEqual(rows[1]["notes"], "Self-contained SQL engine")
                self.assertEqual(rows[1]["created_at"], bm2_created_at)
                self.assertEqual(rows[1]["updated_at"], bm2_updated_at)
            finally:
                conn.close()

            # 5. Start Server 2 pointing to the same db_path on a new ephemeral port
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port2 = server2.server_port
            base2 = f"http://127.0.0.1:{port2}"

            # 6. Verify all previously created bookmarks, updated notes, and timestamps persist
            status_list, list_res = send_http_request(base2, "GET", "/api/bookmarks")
            self.assertEqual(status_list, 200)
            self.assertEqual(len(list_res), 2)

            self.assertEqual(list_res[0]["id"], bm1_id)
            self.assertEqual(list_res[0]["title"], "Python Standard Library")
            self.assertEqual(list_res[0]["url"], "https://docs.python.org/3/library/")
            self.assertEqual(list_res[0]["notes"], "Updated standard library docs")
            self.assertEqual(list_res[0]["created_at"], bm1_created_at)
            self.assertEqual(list_res[0]["updated_at"], bm1_new_updated_at)

            self.assertEqual(list_res[1]["id"], bm2_id)
            self.assertEqual(list_res[1]["title"], "SQLite Official Site")
            self.assertEqual(list_res[1]["url"], "https://www.sqlite.org/")
            self.assertEqual(list_res[1]["notes"], "Self-contained SQL engine")
            self.assertEqual(list_res[1]["created_at"], bm2_created_at)
            self.assertEqual(list_res[1]["updated_at"], bm2_updated_at)

            # Verify query filtering on Server 2
            status_q, q_res = send_http_request(
                base2, "GET", "/api/bookmarks?q=SQLite"
            )
            self.assertEqual(status_q, 200)
            self.assertEqual(len(q_res), 1)
            self.assertEqual(q_res[0]["id"], bm2_id)

            # Verify single retrieval by ID on Server 2
            status_single, single_res = send_http_request(
                base2, "GET", f"/api/bookmarks/{bm1_id}"
            )
            self.assertEqual(status_single, 200)
            self.assertEqual(single_res["notes"], "Updated standard library docs")

        finally:
            # 7. Shuts down Server 2 and cleans up temporary database files
            if server1 is not None:
                try:
                    server1.shutdown()
                    server1.server_close()
                except Exception:
                    pass
            if server2 is not None:
                try:
                    server2.shutdown()
                    server2.server_close()
                except Exception:
                    pass
            temp_dir.cleanup()

    def test_deletion_and_addition_persistence_across_multiple_restarts(self) -> None:
        """Verifies additions and deletions persist across multiple server restart cycles."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "multi_restart.db")
        servers: List[MiniLinksServer] = []

        try:
            # Cycle 1: Add 3 bookmarks
            s1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            servers.append(s1)
            b1 = f"http://127.0.0.1:{s1.server_port}"

            _, bm1 = send_http_request(
                b1, "POST", "/api/bookmarks", {"title": "A", "url": "https://a.org"}
            )
            _, bm2 = send_http_request(
                b1, "POST", "/api/bookmarks", {"title": "B", "url": "https://b.org"}
            )
            _, bm3 = send_http_request(
                b1, "POST", "/api/bookmarks", {"title": "C", "url": "https://c.org"}
            )
            s1.shutdown()
            s1.server_close()

            # Cycle 2: Delete bookmark 2 and add bookmark 4
            s2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            servers.append(s2)
            b2 = f"http://127.0.0.1:{s2.server_port}"

            del_status, _ = send_http_request(
                b2, "DELETE", f"/api/bookmarks/{bm2['id']}"
            )
            self.assertEqual(del_status, 200)

            _, bm4 = send_http_request(
                b2, "POST", "/api/bookmarks", {"title": "D", "url": "https://d.org"}
            )
            s2.shutdown()
            s2.server_close()

            # Cycle 3: Verify remaining bookmarks: 1, 3, and 4
            s3 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            servers.append(s3)
            b3 = f"http://127.0.0.1:{s3.server_port}"

            status, bms = send_http_request(b3, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            ids = [b["id"] for b in bms]
            self.assertEqual(ids, [bm1["id"], bm3["id"], bm4["id"]])
            self.assertNotIn(bm2["id"], ids)

            s3.shutdown()
            s3.server_close()

        finally:
            for s in servers:
                try:
                    s.shutdown()
                    s.server_close()
                except Exception:
                    pass
            temp_dir.cleanup()

    def test_preexisting_sqlite_database_loading(self) -> None:
        """Verifies server initializes properly when given a pre-existing SQLite database."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "preexisting.db")
        server: Optional[MiniLinksServer] = None

        try:
            # Populate database directly using database module
            database.init_db(db_path)
            bm = database.create_bookmark(
                title="Direct DB Bookmark",
                url="https://direct.example.com",
                notes="Created outside server",
                db_path=db_path,
            )

            # Start server with the pre-populated database
            server = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base = f"http://127.0.0.1:{server.server_port}"

            status, bms = send_http_request(base, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            self.assertEqual(len(bms), 1)
            self.assertEqual(bms[0]["id"], bm["id"])
            self.assertEqual(bms[0]["title"], "Direct DB Bookmark")
            self.assertEqual(bms[0]["notes"], "Created outside server")
        finally:
            if server:
                server.shutdown()
                server.server_close()
            temp_dir.cleanup()

    def test_concurrent_read_requests(self) -> None:
        """Verifies concurrent threads reading the SQLite database through the server do not deadlock."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "concurrent.db")
        server: Optional[MiniLinksServer] = None

        try:
            server = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base = f"http://127.0.0.1:{server.server_port}"

            # Create 5 bookmarks
            for i in range(5):
                send_http_request(
                    base,
                    "POST",
                    "/api/bookmarks",
                    {"title": f"Item {i}", "url": f"https://item{i}.com"},
                )

            errors: List[Exception] = []

            def worker() -> None:
                try:
                    for _ in range(5):
                        status, items = send_http_request(base, "GET", "/api/bookmarks")
                        if status != 200 or len(items) != 5:
                            raise ValueError(f"Unexpected response: status={status}, len={len(items)}")
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(errors), 0, f"Concurrent read errors: {errors}")
        finally:
            if server:
                server.shutdown()
                server.server_close()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
