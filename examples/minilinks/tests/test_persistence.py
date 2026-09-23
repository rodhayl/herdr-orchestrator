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

# Ensure examples/minilinks and project root are in sys.path for direct imports
_current_dir = Path(__file__).resolve().parent
_minilinks_dir = _current_dir.parent
_project_root = _minilinks_dir.parent.parent

if str(_project_root) not in sys.path:
    sys.path.append(str(_project_root))
if str(_minilinks_dir) not in sys.path:
    sys.path.insert(0, str(_minilinks_dir))
else:
    sys.path.remove(str(_minilinks_dir))
    sys.path.insert(0, str(_minilinks_dir))

try:
    from app import database
    from app.server import MiniLinksServer, create_server
    if not hasattr(database, "create_bookmark"):
        raise ImportError("Imported wrong database module")
except (ImportError, AttributeError):
    from examples.minilinks.app import database
    from examples.minilinks.app.server import MiniLinksServer, create_server


def send_http_request(
    base_url: str,
    method: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any]:
    """Sends an HTTP request with Connection: close and returns (status_code, parsed_json_response)."""
    headers = {"Connection": "close"}
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
        2. Inserts bookmarks into Server 1 via POST /api/bookmarks and toggles favorite status via PATCH /api/bookmarks/<id>.
        3. Shuts down Server 1 cleanly.
        4. Verifies database file integrity directly using the sqlite3 module, including is_favorite stored as 0 or 1.
        5. Starts Server 2 pointing to the same db_path on a new ephemeral port.
        6. Verifies all previously created bookmarks, updated notes, favorite status, and timestamps persist and are queryable via GET /api/bookmarks.
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
            # Bookmark 1: created without is_favorite (default False)
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
            self.assertIs(created1.get("is_favorite"), False)

            # Bookmark 2: created with explicit is_favorite: False
            bm2_payload = {
                "title": "SQLite Official Site",
                "url": "https://www.sqlite.org/",
                "notes": "Self-contained SQL engine",
                "is_favorite": False,
            }
            status2, created2 = send_http_request(
                base1, "POST", "/api/bookmarks", data=bm2_payload
            )
            self.assertEqual(status2, 201)
            bm2_id = created2["id"]
            bm2_created_at = created2["created_at"]
            bm2_updated_at = created2["updated_at"]
            self.assertIs(created2.get("is_favorite"), False)

            # Bookmark 3: created with explicit is_favorite: True
            bm3_payload = {
                "title": "MDN Web Docs",
                "url": "https://developer.mozilla.org/",
                "notes": "Web standards and APIs",
                "is_favorite": True,
            }
            status3, created3 = send_http_request(
                base1, "POST", "/api/bookmarks", data=bm3_payload
            )
            self.assertEqual(status3, 201)
            bm3_id = created3["id"]
            bm3_created_at = created3["created_at"]
            bm3_updated_at = created3["updated_at"]
            self.assertIs(created3.get("is_favorite"), True)

            # Bookmark 4: created with explicit is_favorite: True, then toggled to False
            bm4_payload = {
                "title": "Temporary Favorite",
                "url": "https://example.com/temp",
                "notes": "Will be unfavorited",
                "is_favorite": True,
            }
            status4, created4 = send_http_request(
                base1, "POST", "/api/bookmarks", data=bm4_payload
            )
            self.assertEqual(status4, 201)
            bm4_id = created4["id"]

            # Sleep briefly to ensure updated_at changes across second boundary
            time.sleep(1.05)

            # Update Bookmark 1 via PATCH: toggle is_favorite to True and update notes
            patch1_payload = {
                "notes": "Updated standard library docs",
                "is_favorite": True,
            }
            patch1_status, patch1_res = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{bm1_id}", data=patch1_payload
            )
            self.assertEqual(patch1_status, 200)
            self.assertIs(patch1_res.get("is_favorite"), True)
            bm1_new_updated_at = patch1_res["updated_at"]
            self.assertNotEqual(bm1_orig_updated_at, bm1_new_updated_at)

            # Update Bookmark 4 via PATCH: toggle is_favorite back to False
            patch4_payload = {"is_favorite": False}
            patch4_status, patch4_res = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{bm4_id}", data=patch4_payload
            )
            self.assertEqual(patch4_status, 200)
            self.assertIs(patch4_res.get("is_favorite"), False)

            # 3. Clean shutdown of Server 1
            server1.shutdown()
            server1.server_close()
            server1 = None

            # 4. Verify database file integrity directly using sqlite3 module
            self.assertTrue(os.path.exists(db_path))
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, title, url, notes, is_favorite, created_at, updated_at
                    FROM bookmarks
                    ORDER BY id ASC
                    """
                )
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 4)

                # Validate row 1 (bm1): updated notes and is_favorite=1 (INTEGER)
                self.assertEqual(rows[0]["id"], bm1_id)
                self.assertEqual(rows[0]["title"], "Python Standard Library")
                self.assertEqual(rows[0]["url"], "https://docs.python.org/3/library/")
                self.assertEqual(rows[0]["notes"], "Updated standard library docs")
                self.assertEqual(rows[0]["is_favorite"], 1)
                self.assertIsInstance(rows[0]["is_favorite"], int)
                self.assertEqual(rows[0]["created_at"], bm1_created_at)
                self.assertEqual(rows[0]["updated_at"], bm1_new_updated_at)

                # Validate row 2 (bm2): is_favorite=0 (INTEGER)
                self.assertEqual(rows[1]["id"], bm2_id)
                self.assertEqual(rows[1]["title"], "SQLite Official Site")
                self.assertEqual(rows[1]["url"], "https://www.sqlite.org/")
                self.assertEqual(rows[1]["notes"], "Self-contained SQL engine")
                self.assertEqual(rows[1]["is_favorite"], 0)
                self.assertIsInstance(rows[1]["is_favorite"], int)
                self.assertEqual(rows[1]["created_at"], bm2_created_at)
                self.assertEqual(rows[1]["updated_at"], bm2_updated_at)

                # Validate row 3 (bm3): is_favorite=1 (INTEGER)
                self.assertEqual(rows[2]["id"], bm3_id)
                self.assertEqual(rows[2]["title"], "MDN Web Docs")
                self.assertEqual(rows[2]["url"], "https://developer.mozilla.org/")
                self.assertEqual(rows[2]["notes"], "Web standards and APIs")
                self.assertEqual(rows[2]["is_favorite"], 1)
                self.assertIsInstance(rows[2]["is_favorite"], int)
                self.assertEqual(rows[2]["created_at"], bm3_created_at)
                self.assertEqual(rows[2]["updated_at"], bm3_updated_at)

                # Validate row 4 (bm4): toggled to is_favorite=0 (INTEGER)
                self.assertEqual(rows[3]["id"], bm4_id)
                self.assertEqual(rows[3]["is_favorite"], 0)
                self.assertIsInstance(rows[3]["is_favorite"], int)
            finally:
                conn.close()

            # 5. Start Server 2 pointing to the same db_path on a new ephemeral port
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            port2 = server2.server_port
            base2 = f"http://127.0.0.1:{port2}"

            # 6. Verify all previously created bookmarks, updated notes, favorite status, and timestamps persist
            status_list, list_res = send_http_request(base2, "GET", "/api/bookmarks")
            self.assertEqual(status_list, 200)
            self.assertEqual(len(list_res), 4)

            # Check bookmark 1 on Server 2
            self.assertEqual(list_res[0]["id"], bm1_id)
            self.assertEqual(list_res[0]["title"], "Python Standard Library")
            self.assertEqual(list_res[0]["url"], "https://docs.python.org/3/library/")
            self.assertEqual(list_res[0]["notes"], "Updated standard library docs")
            self.assertIs(list_res[0]["is_favorite"], True)
            self.assertIsInstance(list_res[0]["is_favorite"], bool)
            self.assertEqual(list_res[0]["created_at"], bm1_created_at)
            self.assertEqual(list_res[0]["updated_at"], bm1_new_updated_at)

            # Check bookmark 2 on Server 2
            self.assertEqual(list_res[1]["id"], bm2_id)
            self.assertEqual(list_res[1]["title"], "SQLite Official Site")
            self.assertEqual(list_res[1]["url"], "https://www.sqlite.org/")
            self.assertEqual(list_res[1]["notes"], "Self-contained SQL engine")
            self.assertIs(list_res[1]["is_favorite"], False)
            self.assertIsInstance(list_res[1]["is_favorite"], bool)
            self.assertEqual(list_res[1]["created_at"], bm2_created_at)
            self.assertEqual(list_res[1]["updated_at"], bm2_updated_at)

            # Check bookmark 3 on Server 2
            self.assertEqual(list_res[2]["id"], bm3_id)
            self.assertIs(list_res[2]["is_favorite"], True)
            self.assertIsInstance(list_res[2]["is_favorite"], bool)

            # Check bookmark 4 on Server 2
            self.assertEqual(list_res[3]["id"], bm4_id)
            self.assertIs(list_res[3]["is_favorite"], False)
            self.assertIsInstance(list_res[3]["is_favorite"], bool)

            # Verify favorite filtering on Server 2
            status_fav, fav_res = send_http_request(
                base2, "GET", "/api/bookmarks?favorites=true"
            )
            self.assertEqual(status_fav, 200)
            self.assertEqual(len(fav_res), 2)
            self.assertEqual([b["id"] for b in fav_res], [bm1_id, bm3_id])
            for b in fav_res:
                self.assertIs(b["is_favorite"], True)

            # Verify query filtering combined with favorites on Server 2
            status_combo, combo_res = send_http_request(
                base2, "GET", "/api/bookmarks?favorites=true&q=Python"
            )
            self.assertEqual(status_combo, 200)
            self.assertEqual(len(combo_res), 1)
            self.assertEqual(combo_res[0]["id"], bm1_id)

            # Verify single retrieval by ID on Server 2
            status_single1, single_res1 = send_http_request(
                base2, "GET", f"/api/bookmarks/{bm1_id}"
            )
            self.assertEqual(status_single1, 200)
            self.assertEqual(single_res1["notes"], "Updated standard library docs")
            self.assertIs(single_res1["is_favorite"], True)

            status_single2, single_res2 = send_http_request(
                base2, "GET", f"/api/bookmarks/{bm2_id}"
            )
            self.assertEqual(status_single2, 200)
            self.assertEqual(single_res2["notes"], "Self-contained SQL engine")
            self.assertIs(single_res2["is_favorite"], False)

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

    def test_notes_persistence_across_server_restart(self) -> None:
        """
        Validates that bookmark notes persist accurately across SQLite database server restarts:
        1. Starts Server 1 on an ephemeral port with a temporary db_path.
        2. Inserts bookmarks with varied notes (multiline, markdown, standard, omitted, null, empty).
        3. Updates notes via PATCH (modifying notes and clearing notes).
        4. Shuts down Server 1 cleanly.
        5. Verifies database file integrity directly using sqlite3 module while server is stopped.
        6. Starts Server 2 pointing to the same db_path on a new ephemeral port.
        7. Verifies all notes persist accurately via GET /api/bookmarks and GET /api/bookmarks/<id>.
        8. Verifies notes search filtering works accurately on Server 2.
        9. Mutates notes on Server 2, restarts into Server 3, and verifies persisted changes.
        10. Shuts down servers and cleans up.
        """
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "notes_persistence.db")
        server1: Optional[MiniLinksServer] = None
        server2: Optional[MiniLinksServer] = None
        server3: Optional[MiniLinksServer] = None

        try:
            # 1. Start Server 1 on an ephemeral port
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base1 = f"http://127.0.0.1:{server1.server_port}"

            # 2. Insert bookmarks into Server 1
            # BM1: Multiline notes with newlines and indentation
            bm1_notes = "Line 1: Project Architecture\nLine 2: SQLite Persistence\n  - ACID Compliant\n  - Embedded Engine\nLine 3: Conclusion"
            status1, bm1 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {
                    "title": "BM1 Multiline",
                    "url": "https://bm1.example.com",
                    "notes": bm1_notes,
                    "is_favorite": True,
                },
            )
            self.assertEqual(status1, 201)
            bm1_id = bm1["id"]

            # BM2: Markdown with special characters and tags
            bm2_notes = "## Documentation Guide\n* Bullet 1\n* Bullet 2\nTags: #python #sqlite (test <>&'\"/)"
            status2, bm2 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {
                    "title": "BM2 Markdown",
                    "url": "https://bm2.example.com",
                    "notes": bm2_notes,
                    "is_favorite": False,
                },
            )
            self.assertEqual(status2, 201)
            bm2_id = bm2["id"]

            # BM3: Standard single-line notes
            bm3_notes = "Standard concise bookmark note"
            status3, bm3 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "BM3 Standard", "url": "https://bm3.example.com", "notes": bm3_notes},
            )
            self.assertEqual(status3, 201)
            bm3_id = bm3["id"]

            # BM4: Omitted notes (default empty string)
            status4, bm4 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "BM4 Omitted Notes", "url": "https://bm4.example.com"},
            )
            self.assertEqual(status4, 201)
            bm4_id = bm4["id"]
            self.assertEqual(bm4["notes"], "")

            # BM5: Explicit None notes (default empty string)
            status5, bm5 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "BM5 Null Notes", "url": "https://bm5.example.com", "notes": None},
            )
            self.assertEqual(status5, 201)
            bm5_id = bm5["id"]
            self.assertEqual(bm5["notes"], "")

            # BM6: Initial notes that will be updated
            status6, bm6 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "BM6 To Be Updated", "url": "https://bm6.example.com", "notes": "Initial BM6 Note"},
            )
            self.assertEqual(status6, 201)
            bm6_id = bm6["id"]

            # BM7: Initial notes that will be cleared
            status7, bm7 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "BM7 To Be Cleared", "url": "https://bm7.example.com", "notes": "Initial BM7 Note"},
            )
            self.assertEqual(status7, 201)
            bm7_id = bm7["id"]

            # 3. Update BM6 and BM7 via PATCH on Server 1
            updated_bm6_notes = "Updated BM6 Note: New Research Content"
            patch6_status, patch6_res = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{bm6_id}", {"notes": updated_bm6_notes}
            )
            self.assertEqual(patch6_status, 200)
            self.assertEqual(patch6_res["notes"], updated_bm6_notes)

            # Clear notes on BM7 by sending ""
            patch7_status, patch7_res = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{bm7_id}", {"notes": ""}
            )
            self.assertEqual(patch7_status, 200)
            self.assertEqual(patch7_res["notes"], "")

            # 4. Clean shutdown of Server 1
            server1.shutdown()
            server1.server_close()
            server1 = None

            # 5. Verify database file integrity directly using sqlite3 module while offline
            self.assertTrue(os.path.exists(db_path))
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(bookmarks)")
                cols = {row["name"]: row["type"].upper() for row in cursor.fetchall()}
                self.assertIn("notes", cols)
                self.assertIn("TEXT", cols["notes"])

                cursor.execute("SELECT id, title, url, notes, is_favorite FROM bookmarks ORDER BY id ASC")
                db_rows = cursor.fetchall()
                self.assertEqual(len(db_rows), 7)

                notes_by_id = {row["id"]: row["notes"] for row in db_rows}
                self.assertEqual(notes_by_id[bm1_id], bm1_notes)
                self.assertEqual(notes_by_id[bm2_id], bm2_notes)
                self.assertEqual(notes_by_id[bm3_id], bm3_notes)
                self.assertEqual(notes_by_id[bm4_id], "")
                self.assertEqual(notes_by_id[bm5_id], "")
                self.assertEqual(notes_by_id[bm6_id], updated_bm6_notes)
                self.assertEqual(notes_by_id[bm7_id], "")
            finally:
                conn.close()

            # 6. Start Server 2 pointing to the same db_path on a new ephemeral port
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base2 = f"http://127.0.0.1:{server2.server_port}"

            # 7. Verify all bookmarks and notes via GET /api/bookmarks on Server 2
            status_list, list_res = send_http_request(base2, "GET", "/api/bookmarks")
            self.assertEqual(status_list, 200)
            self.assertEqual(len(list_res), 7)

            api_notes_by_id = {b["id"]: b["notes"] for b in list_res}
            self.assertEqual(api_notes_by_id[bm1_id], bm1_notes)
            self.assertEqual(api_notes_by_id[bm2_id], bm2_notes)
            self.assertEqual(api_notes_by_id[bm3_id], bm3_notes)
            self.assertEqual(api_notes_by_id[bm4_id], "")
            self.assertEqual(api_notes_by_id[bm5_id], "")
            self.assertEqual(api_notes_by_id[bm6_id], updated_bm6_notes)
            self.assertEqual(api_notes_by_id[bm7_id], "")

            # Ensure all notes are strings and never None
            for b in list_res:
                self.assertIsInstance(b["notes"], str)

            # Verify GET /api/bookmarks/<id> for individual bookmarks
            status_single1, single1 = send_http_request(base2, "GET", f"/api/bookmarks/{bm1_id}")
            self.assertEqual(status_single1, 200)
            self.assertEqual(single1["notes"], bm1_notes)

            status_single7, single7 = send_http_request(base2, "GET", f"/api/bookmarks/{bm7_id}")
            self.assertEqual(status_single7, 200)
            self.assertEqual(single7["notes"], "")

            # 8. Verify search filtering across persisted notes on Server 2
            # Match multiline notes term
            status_q1, q1_res = send_http_request(base2, "GET", "/api/bookmarks?q=Architecture")
            self.assertEqual(status_q1, 200)
            self.assertEqual(len(q1_res), 1)
            self.assertEqual(q1_res[0]["id"], bm1_id)

            # Match markdown notes term
            status_q2, q2_res = send_http_request(base2, "GET", "/api/bookmarks?q=Documentation")
            self.assertEqual(status_q2, 200)
            self.assertEqual(len(q2_res), 1)
            self.assertEqual(q2_res[0]["id"], bm2_id)

            # Match updated notes term
            status_q6, q6_res = send_http_request(
                base2, "GET", f"/api/bookmarks?q={urllib.parse.quote('Research Content')}"
            )
            self.assertEqual(status_q6, 200)
            self.assertEqual(len(q6_res), 1)
            self.assertEqual(q6_res[0]["id"], bm6_id)

            # 9. Mutate notes on Server 2: update BM4 (was empty) to have notes, restart into Server 3
            send_http_request(base2, "PATCH", f"/api/bookmarks/{bm4_id}", {"notes": "BM4 now has notes on S2"})

            server2.shutdown()
            server2.server_close()
            server2 = None

            # Start Server 3
            server3 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base3 = f"http://127.0.0.1:{server3.server_port}"

            status_s3, bm4_s3 = send_http_request(base3, "GET", f"/api/bookmarks/{bm4_id}")
            self.assertEqual(status_s3, 200)
            self.assertEqual(bm4_s3["notes"], "BM4 now has notes on S2")

            server3.shutdown()
            server3.server_close()
            server3 = None

        finally:
            for s in [server1, server2, server3]:
                if s is not None:
                    try:
                        s.shutdown()
                        s.server_close()
                    except Exception:
                        pass
            temp_dir.cleanup()

    def test_sqlite_backward_compatibility_migration_notes(self) -> None:
        """Verifies database migration automatically adds notes column when opening an older SQLite database lacking notes."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "legacy_no_notes.db")
        server1: Optional[MiniLinksServer] = None
        server2: Optional[MiniLinksServer] = None

        try:
            # 1. Create a legacy table schema WITHOUT notes column
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("""
                    CREATE TABLE bookmarks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL,
                        is_favorite INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute(
                    """
                    INSERT INTO bookmarks (title, url, is_favorite, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "Legacy Without Notes",
                        "https://legacy-no-notes.example.com",
                        1,
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                    ),
                )
            conn.close()

            # 2. Start Server 1 (should automatically migrate schema adding notes column)
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base1 = f"http://127.0.0.1:{server1.server_port}"

            # Verify legacy bookmark returns with notes=""
            status, bms = send_http_request(base1, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            self.assertEqual(len(bms), 1)
            legacy_id = bms[0]["id"]
            self.assertEqual(bms[0]["title"], "Legacy Without Notes")
            self.assertEqual(bms[0]["notes"], "")
            self.assertIs(bms[0]["is_favorite"], True)

            # Update legacy bookmark notes via PATCH
            status_patch, patched = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{legacy_id}", {"notes": "Added notes to legacy record"}
            )
            self.assertEqual(status_patch, 200)
            self.assertEqual(patched["notes"], "Added notes to legacy record")

            # Clean shutdown Server 1
            server1.shutdown()
            server1.server_close()
            server1 = None

            # 3. Direct SQLite verification
            conn2 = sqlite3.connect(db_path)
            try:
                cursor = conn2.cursor()
                cursor.execute("PRAGMA table_info(bookmarks)")
                col_names = [col[1] for col in cursor.fetchall()]
                self.assertIn("notes", col_names)

                cursor.execute("SELECT id, notes FROM bookmarks WHERE id = ?", (legacy_id,))
                row = cursor.fetchone()
                self.assertEqual(row[1], "Added notes to legacy record")
            finally:
                conn2.close()

            # 4. Start Server 2 pointing to the same migrated DB
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base2 = f"http://127.0.0.1:{server2.server_port}"

            status_get, bm_get = send_http_request(base2, "GET", f"/api/bookmarks/{legacy_id}")
            self.assertEqual(status_get, 200)
            self.assertEqual(bm_get["notes"], "Added notes to legacy record")

            server2.shutdown()
            server2.server_close()
            server2 = None

        finally:
            if server1:
                try:
                    server1.shutdown()
                    server1.server_close()
                except Exception:
                    pass
            if server2:
                try:
                    server2.shutdown()
                    server2.server_close()
                except Exception:
                    pass
            temp_dir.cleanup()

    def test_favorite_persistence_and_mutations_across_multiple_restarts(self) -> None:
        """Verifies favorite status toggles and mutations persist across three consecutive server restart lifecycles."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "multi_restart_favorites.db")
        servers: List[MiniLinksServer] = []

        try:
            # Lifecycle 1: Start Server 1, create 3 bookmarks, favorite BM1 and BM2
            s1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            servers.append(s1)
            b1 = f"http://127.0.0.1:{s1.server_port}"

            _, bm1 = send_http_request(
                b1,
                "POST",
                "/api/bookmarks",
                {"title": "Alpha", "url": "https://alpha.example.com", "is_favorite": True},
            )
            _, bm2 = send_http_request(
                b1,
                "POST",
                "/api/bookmarks",
                {"title": "Beta", "url": "https://beta.example.com", "is_favorite": False},
            )
            _, bm3 = send_http_request(
                b1,
                "POST",
                "/api/bookmarks",
                {"title": "Gamma", "url": "https://gamma.example.com"},
            )
            # Toggle BM2 to True on Server 1
            send_http_request(b1, "PATCH", f"/api/bookmarks/{bm2['id']}", {"is_favorite": True})

            # Verify Server 1 favorite list: BM1 and BM2
            _, favs1 = send_http_request(b1, "GET", "/api/bookmarks?favorites=true")
            self.assertEqual([b["id"] for b in favs1], [bm1["id"], bm2["id"]])

            s1.shutdown()
            s1.server_close()

            # Lifecycle 2: Start Server 2, verify favorites, unfavorite BM1, favorite BM3, create BM4 as favorite
            s2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            servers.append(s2)
            b2 = f"http://127.0.0.1:{s2.server_port}"

            # Verify persisted favorites on Server 2
            _, favs2_init = send_http_request(b2, "GET", "/api/bookmarks?favorites=true")
            self.assertEqual([b["id"] for b in favs2_init], [bm1["id"], bm2["id"]])

            # Unfavorite BM1
            send_http_request(b2, "PATCH", f"/api/bookmarks/{bm1['id']}", {"is_favorite": False})
            # Favorite BM3
            send_http_request(b2, "PATCH", f"/api/bookmarks/{bm3['id']}", {"is_favorite": True})
            # Create BM4 as favorite
            _, bm4 = send_http_request(
                b2,
                "POST",
                "/api/bookmarks",
                {"title": "Delta", "url": "https://delta.example.com", "is_favorite": True},
            )

            # Verify favorites on Server 2: BM2, BM3, BM4
            _, favs2 = send_http_request(b2, "GET", "/api/bookmarks?favorites=true")
            self.assertEqual([b["id"] for b in favs2], [bm2["id"], bm3["id"], bm4["id"]])

            s2.shutdown()
            s2.server_close()

            # Inspect SQLite database directly between restarts
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id, is_favorite FROM bookmarks ORDER BY id ASC")
                rows = cursor.fetchall()
                fav_map = {row["id"]: row["is_favorite"] for row in rows}
                self.assertEqual(fav_map[bm1["id"]], 0)
                self.assertEqual(fav_map[bm2["id"]], 1)
                self.assertEqual(fav_map[bm3["id"]], 1)
                self.assertEqual(fav_map[bm4["id"]], 1)
            finally:
                conn.close()

            # Lifecycle 3: Start Server 3, verify favorites and full listing
            s3 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            servers.append(s3)
            b3 = f"http://127.0.0.1:{s3.server_port}"

            _, favs3 = send_http_request(b3, "GET", "/api/bookmarks?favorites=true")
            self.assertEqual([b["id"] for b in favs3], [bm2["id"], bm3["id"], bm4["id"]])

            _, all_bms3 = send_http_request(b3, "GET", "/api/bookmarks")
            self.assertEqual(len(all_bms3), 4)
            bms_map = {b["id"]: b["is_favorite"] for b in all_bms3}
            self.assertIs(bms_map[bm1["id"]], False)
            self.assertIs(bms_map[bm2["id"]], True)
            self.assertIs(bms_map[bm3["id"]], True)
            self.assertIs(bms_map[bm4["id"]], True)

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
        """Verifies server initializes properly and serves is_favorite from a pre-existing SQLite database."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "preexisting.db")
        server: Optional[MiniLinksServer] = None

        try:
            # Populate database directly using database module
            database.init_db(db_path)
            bm1 = database.create_bookmark(
                title="Direct DB Non-Fav Bookmark",
                url="https://direct-nonfav.example.com",
                notes="Created outside server without favorite",
                is_favorite=False,
                db_path=db_path,
            )
            bm2 = database.create_bookmark(
                title="Direct DB Favorite Bookmark",
                url="https://direct-fav.example.com",
                notes="Created outside server with favorite",
                is_favorite=True,
                db_path=db_path,
            )

            # Start server with the pre-populated database
            server = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base = f"http://127.0.0.1:{server.server_port}"

            # Verify GET /api/bookmarks
            status, bms = send_http_request(base, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            self.assertEqual(len(bms), 2)
            self.assertEqual(bms[0]["id"], bm1["id"])
            self.assertIs(bms[0]["is_favorite"], False)
            self.assertEqual(bms[1]["id"], bm2["id"])
            self.assertIs(bms[1]["is_favorite"], True)

            # Verify GET /api/bookmarks?favorites=true returns only the favorited one
            status_fav, fav_bms = send_http_request(base, "GET", "/api/bookmarks?favorites=true")
            self.assertEqual(status_fav, 200)
            self.assertEqual(len(fav_bms), 1)
            self.assertEqual(fav_bms[0]["id"], bm2["id"])
            self.assertIs(fav_bms[0]["is_favorite"], True)

            # Verify GET /api/bookmarks/<id> returns boolean is_favorite
            status_single1, single1 = send_http_request(base, "GET", f"/api/bookmarks/{bm1['id']}")
            self.assertEqual(status_single1, 200)
            self.assertIs(single1["is_favorite"], False)

            status_single2, single2 = send_http_request(base, "GET", f"/api/bookmarks/{bm2['id']}")
            self.assertEqual(status_single2, 200)
            self.assertIs(single2["is_favorite"], True)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            temp_dir.cleanup()

    def test_sqlite_backward_compatibility_migration(self) -> None:
        """Verifies database migration automatically adds is_favorite column when opening an older SQLite database."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "legacy_schema.db")
        server1: Optional[MiniLinksServer] = None
        server2: Optional[MiniLinksServer] = None

        try:
            # 1. Create a legacy table schema WITHOUT is_favorite column
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("""
                    CREATE TABLE bookmarks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL,
                        notes TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute(
                    """
                    INSERT INTO bookmarks (title, url, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "Legacy Bookmark",
                        "https://legacy.example.com",
                        "Created on old schema",
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                    ),
                )
            conn.close()

            # 2. Start Server 1 (should automatically migrate schema)
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base1 = f"http://127.0.0.1:{server1.server_port}"

            # Verify legacy bookmark returns with is_favorite=False
            status, bms = send_http_request(base1, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            self.assertEqual(len(bms), 1)
            legacy_id = bms[0]["id"]
            self.assertEqual(bms[0]["title"], "Legacy Bookmark")
            self.assertIs(bms[0]["is_favorite"], False)

            # Toggle legacy bookmark to favorite via PATCH
            status_patch, patched = send_http_request(
                base1, "PATCH", f"/api/bookmarks/{legacy_id}", {"is_favorite": True}
            )
            self.assertEqual(status_patch, 200)
            self.assertIs(patched["is_favorite"], True)

            # Clean shutdown Server 1
            server1.shutdown()
            server1.server_close()
            server1 = None

            # 3. Direct SQLite verification of the migrated column and value
            conn2 = sqlite3.connect(db_path)
            try:
                cursor = conn2.cursor()
                cursor.execute("PRAGMA table_info(bookmarks)")
                col_names = [col[1] for col in cursor.fetchall()]
                self.assertIn("is_favorite", col_names)

                cursor.execute("SELECT id, is_favorite FROM bookmarks WHERE id = ?", (legacy_id,))
                row = cursor.fetchone()
                self.assertEqual(row[1], 1)
            finally:
                conn2.close()

            # 4. Start Server 2 pointing to the same migrated DB
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base2 = f"http://127.0.0.1:{server2.server_port}"

            # Verify persisted favorite on Server 2
            status_fav, favs = send_http_request(base2, "GET", "/api/bookmarks?favorites=true")
            self.assertEqual(status_fav, 200)
            self.assertEqual(len(favs), 1)
            self.assertEqual(favs[0]["id"], legacy_id)
            self.assertIs(favs[0]["is_favorite"], True)

            server2.shutdown()
            server2.server_close()
            server2 = None

        finally:
            if server1:
                try:
                    server1.shutdown()
                    server1.server_close()
                except Exception:
                    pass
            if server2:
                try:
                    server2.shutdown()
                    server2.server_close()
                except Exception:
                    pass
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

    def test_tags_persistence_across_server_restart(self) -> None:
        """Validates bookmark tags persistence across server restarts and direct SQLite inspection."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "tags_persistence.db")
        server1: Optional[MiniLinksServer] = None
        server2: Optional[MiniLinksServer] = None

        try:
            # 1. Start Server 1
            server1 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base1 = f"http://127.0.0.1:{server1.server_port}"

            # Insert bookmark 1 with tags
            status1, bm1 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "Python Docs", "url": "https://docs.python.org", "tags": ["python", "stdlib"]},
            )
            self.assertEqual(status1, 201)
            bm1_id = bm1["id"]

            # Insert bookmark 2 without tags (default empty list)
            status2, bm2 = send_http_request(
                base1,
                "POST",
                "/api/bookmarks",
                {"title": "Web Specs", "url": "https://w3.org"},
            )
            self.assertEqual(status2, 201)
            bm2_id = bm2["id"]
            self.assertEqual(bm2["tags"], [])

            # Update bookmark 2 with tags via PATCH
            status2_patch, bm2_patched = send_http_request(
                base1,
                "PATCH",
                f"/api/bookmarks/{bm2_id}",
                {"tags": ["web", "standards"]},
            )
            self.assertEqual(status2_patch, 200)
            self.assertEqual(bm2_patched["tags"], ["web", "standards"])

            # 2. Shut down Server 1
            server1.shutdown()
            server1.server_close()
            server1 = None

            # 3. Direct SQLite database inspection
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id, tags FROM bookmarks ORDER BY id ASC")
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 2)
                # BM1
                self.assertEqual(rows[0][0], bm1_id)
                bm1_tags_db = json.loads(rows[0][1])
                self.assertEqual(bm1_tags_db, ["python", "stdlib"])
                # BM2
                self.assertEqual(rows[1][0], bm2_id)
                bm2_tags_db = json.loads(rows[1][1])
                self.assertEqual(bm2_tags_db, ["web", "standards"])
            finally:
                conn.close()

            # 4. Start Server 2 pointing to same database
            server2 = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base2 = f"http://127.0.0.1:{server2.server_port}"

            # Verify GET /api/bookmarks
            status_list, bookmarks = send_http_request(base2, "GET", "/api/bookmarks")
            self.assertEqual(status_list, 200)
            self.assertEqual(len(bookmarks), 2)
            self.assertEqual(bookmarks[0]["tags"], ["python", "stdlib"])
            self.assertEqual(bookmarks[1]["tags"], ["web", "standards"])

            # Verify GET /api/tags
            status_tags, tags_res = send_http_request(base2, "GET", "/api/tags")
            self.assertEqual(status_tags, 200)
            self.assertEqual(tags_res, {"tags": ["python", "standards", "stdlib", "web"]})

            # Verify GET /api/bookmarks?tag=python
            status_tag, filtered = send_http_request(base2, "GET", "/api/bookmarks?tag=python")
            self.assertEqual(status_tag, 200)
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["id"], bm1_id)
        finally:
            if server1:
                try:
                    server1.shutdown()
                    server1.server_close()
                except Exception:
                    pass
            if server2:
                try:
                    server2.shutdown()
                    server2.server_close()
                except Exception:
                    pass
            temp_dir.cleanup()

    def test_sqlite_backward_compatibility_migration_tags(self) -> None:
        """Verifies automatic database migration adds tags column to older SQLite schema lacking tags."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "legacy_no_tags.db")
        server: Optional[MiniLinksServer] = None

        try:
            # 1. Create legacy table without tags column
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("""
                    CREATE TABLE bookmarks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL,
                        notes TEXT DEFAULT '',
                        is_favorite INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute(
                    """
                    INSERT INTO bookmarks (title, url, notes, is_favorite, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Legacy Without Tags",
                        "https://legacy.example.com",
                        "Legacy Notes",
                        0,
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                    ),
                )
            conn.close()

            # 2. Start server which executes migration
            server = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base = f"http://127.0.0.1:{server.server_port}"

            # 3. Verify legacy bookmark is readable with default tags=[]
            status, bookmarks = send_http_request(base, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            self.assertEqual(len(bookmarks), 1)
            self.assertEqual(bookmarks[0]["tags"], [])

            # 4. Verify GET /api/tags returns empty list
            status_tags, tags_res = send_http_request(base, "GET", "/api/tags")
            self.assertEqual(status_tags, 200)
            self.assertEqual(tags_res, {"tags": []})

            # 5. Insert new bookmark with tags
            status_new, created = send_http_request(
                base,
                "POST",
                "/api/bookmarks",
                {"title": "New", "url": "https://new.com", "tags": ["migrated"]},
            )
            self.assertEqual(status_new, 201)
            self.assertEqual(created["tags"], ["migrated"])

            # 6. Verify tags endpoint now includes the new tag
            _, tags_updated = send_http_request(base, "GET", "/api/tags")
            self.assertEqual(tags_updated, {"tags": ["migrated"]})
        finally:
            if server:
                server.shutdown()
                server.server_close()
            temp_dir.cleanup()

    def test_sqlite_backward_compatibility_migration_archived(self) -> None:
        """Verifies automatic database migration adds archived column to older SQLite schema lacking archived."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "legacy_no_archived.db")
        server: Optional[MiniLinksServer] = None

        try:
            # 1. Create legacy table without archived column
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("""
                    CREATE TABLE bookmarks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL,
                        notes TEXT DEFAULT '',
                        tags TEXT DEFAULT '[]',
                        is_favorite INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute(
                    """
                    INSERT INTO bookmarks (title, url, notes, tags, is_favorite, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Legacy Without Archived",
                        "https://legacy-archived.example.com",
                        "Legacy Notes",
                        '["old"]',
                        0,
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                    ),
                )
            conn.close()

            # 2. Start server which executes migration
            server = create_server(host="127.0.0.1", port=0, db_path=db_path)
            base = f"http://127.0.0.1:{server.server_port}"

            # 3. Verify legacy bookmark is readable with default archived=False
            status, bookmarks = send_http_request(base, "GET", "/api/bookmarks")
            self.assertEqual(status, 200)
            self.assertEqual(len(bookmarks), 1)
            self.assertEqual(bookmarks[0]["archived"], False)

            # 4. Archive legacy bookmark via POST /api/bookmarks/<id>/archive
            bm_id = bookmarks[0]["id"]
            status_arch, arch_res = send_http_request(base, "POST", f"/api/bookmarks/{bm_id}/archive")
            self.assertEqual(status_arch, 200)
            self.assertEqual(arch_res["archived"], True)

            # 5. Verify default GET /api/bookmarks now returns 0 items (active only)
            status_def, bms_def = send_http_request(base, "GET", "/api/bookmarks")
            self.assertEqual(status_def, 200)
            self.assertEqual(len(bms_def), 0)

            # 6. Verify GET /api/bookmarks?archived=true returns the archived bookmark
            status_arch_q, bms_arch_q = send_http_request(base, "GET", "/api/bookmarks?archived=true")
            self.assertEqual(status_arch_q, 200)
            self.assertEqual(len(bms_arch_q), 1)
            self.assertEqual(bms_arch_q[0]["archived"], True)

            # 7. Restore legacy bookmark via POST /api/bookmarks/<id>/restore
            status_rest, rest_res = send_http_request(base, "POST", f"/api/bookmarks/{bm_id}/restore")
            self.assertEqual(status_rest, 200)
            self.assertEqual(rest_res["archived"], False)

            # 8. Verify default GET /api/bookmarks returns it again
            status_def2, bms_def2 = send_http_request(base, "GET", "/api/bookmarks")
            self.assertEqual(status_def2, 200)
            self.assertEqual(len(bms_def2), 1)
            self.assertEqual(bms_def2[0]["archived"], False)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
