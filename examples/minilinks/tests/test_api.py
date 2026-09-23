"""Unit and integration test suite for MiniLinks REST API and static asset serving."""

import http.client
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
from typing import Any, Dict, Optional, Tuple

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


class TestMiniLinksAPI(unittest.TestCase):
    """Test suite verifying all REST API endpoints, static file serving, and concurrency."""

    def setUp(self) -> None:
        """Starts an isolated MiniLinks server instance with a temporary database."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_minilinks.db")
        self.server: MiniLinksServer = create_server(
            host="127.0.0.1",
            port=0,
            db_path=self.db_path,
        )
        self.port: int = self.server.server_port
        self.base_url: str = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        """Shuts down the server and cleans up temporary database files."""
        if hasattr(self, "server") and self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
        if hasattr(self, "temp_dir") and self.temp_dir:
            try:
                self.temp_dir.cleanup()
            except Exception:
                pass

    def make_request(
        self,
        method: str,
        path: str,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Any, Dict[str, str], bytes]:
        """
        Sends an HTTP request to the running server.
        Returns (status_code, parsed_json_or_none, response_headers, raw_body).
        """
        req_headers = {"Connection": "close"}
        if headers:
            req_headers.update(headers)
        body_bytes: Optional[bytes] = None

        if data is not None:
            if isinstance(data, (dict, list)):
                body_bytes = json.dumps(data).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json")
            elif isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data

        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url, data=body_bytes, headers=req_headers, method=method
        )

        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                body = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            resp_headers = {k.lower(): v for k, v in e.headers.items()}
            body = e.read()

        parsed_json = None
        if body:
            try:
                parsed_json = json.loads(body.decode("utf-8"))
            except Exception:
                parsed_json = None

        return status, parsed_json, resp_headers, body

    def raw_request(
        self,
        method: str,
        raw_path: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Sends a raw HTTP request without urllib path normalization."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        req_headers = {"Connection": "close"}
        if headers:
            req_headers.update(headers)
        try:
            conn.request(method, raw_path, body=body, headers=req_headers)
            resp = conn.getresponse()
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            resp_body = resp.read()
            return status, resp_headers, resp_body
        finally:
            conn.close()

    # 1. Health endpoint
    def test_health_check(self) -> None:
        """Verifies GET /health returns 200 OK and status ok payload."""
        status, payload, headers, _ = self.make_request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("status"), "ok")
        self.assertIn("application/json", headers.get("content-type", ""))

    # 2. Initial empty bookmark listing
    def test_initial_bookmarks_empty(self) -> None:
        """Verifies GET /api/bookmarks returns 200 and an empty list initially."""
        status, payload, _, _ = self.make_request("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 0)

    # 3. Create bookmark (valid) and direct SQLite verification
    def test_create_bookmark_valid(self) -> None:
        """Verifies POST /api/bookmarks creates a bookmark, returns 201, and writes to SQLite with is_favorite=False."""
        data = {
            "title": "Python Documentation",
            "url": "https://docs.python.org/3/",
            "notes": "Official standard library reference",
        }
        status, payload, headers, _ = self.make_request(
            "POST", "/api/bookmarks", data=data
        )
        self.assertEqual(status, 201)
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload.get("id"), int)
        self.assertGreater(payload["id"], 0)
        self.assertEqual(payload.get("title"), "Python Documentation")
        self.assertEqual(payload.get("url"), "https://docs.python.org/3/")
        self.assertEqual(
            payload.get("notes"), "Official standard library reference"
        )
        # Verify is_favorite defaults to native False
        self.assertIn("is_favorite", payload)
        self.assertIs(payload["is_favorite"], False)
        self.assertIsInstance(payload["is_favorite"], bool)
        self.assertTrue(payload.get("created_at"))
        self.assertTrue(payload.get("updated_at"))
        self.assertEqual(payload["created_at"], payload["updated_at"])
        self.assertIn("application/json", headers.get("content-type", ""))

        # Direct database inspection using sqlite3 module
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, url, notes, is_favorite FROM bookmarks WHERE id = ?",
                (payload["id"],),
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], payload["id"])
            self.assertEqual(row[1], "Python Documentation")
            self.assertEqual(row[2], "https://docs.python.org/3/")
            self.assertEqual(row[3], "Official standard library reference")
            self.assertEqual(row[4], 0)
        finally:
            conn.close()

    def test_create_bookmark_default_notes(self) -> None:
        """Verifies POST /api/bookmarks handles omitted or None notes with empty string default."""
        data1 = {
            "title": "MDN Web Docs",
            "url": "https://developer.mozilla.org/",
        }
        status1, payload1, _, _ = self.make_request(
            "POST", "/api/bookmarks", data=data1
        )
        self.assertEqual(status1, 201)
        self.assertEqual(payload1.get("notes"), "")
        self.assertIs(payload1.get("is_favorite"), False)

        data2 = {
            "title": "SQLite Tutorial",
            "url": "https://www.sqlite.org/",
            "notes": None,
        }
        status2, payload2, _, _ = self.make_request(
            "POST", "/api/bookmarks", data=data2
        )
        self.assertEqual(status2, 201)
        self.assertEqual(payload2.get("notes"), "")
        self.assertIs(payload2.get("is_favorite"), False)

    def test_create_bookmark_default_is_favorite(self) -> None:
        """Verifies newly created bookmarks have is_favorite=False by default."""
        data = {
            "title": "Default Favorite Test",
            "url": "https://example.com/default-fav",
        }
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data=data
        )
        self.assertEqual(status, 201)
        self.assertIn("is_favorite", payload)
        self.assertIs(payload["is_favorite"], False)
        self.assertIsInstance(payload["is_favorite"], bool)

        # Direct database inspection
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_favorite FROM bookmarks WHERE id = ?",
                (payload["id"],),
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 0)
        finally:
            conn.close()

    def test_create_bookmark_with_explicit_is_favorite(self) -> None:
        """Verifies creating bookmarks with explicit boolean is_favorite (True or False)."""
        # Create with is_favorite = True
        data_true = {
            "title": "Favorite Bookmark",
            "url": "https://example.com/fav",
            "is_favorite": True,
        }
        status_true, payload_true, _, _ = self.make_request(
            "POST", "/api/bookmarks", data=data_true
        )
        self.assertEqual(status_true, 201)
        self.assertIs(payload_true.get("is_favorite"), True)
        self.assertIsInstance(payload_true.get("is_favorite"), bool)

        # Create with is_favorite = False
        data_false = {
            "title": "Non-Favorite Bookmark",
            "url": "https://example.com/non-fav",
            "is_favorite": False,
        }
        status_false, payload_false, _, _ = self.make_request(
            "POST", "/api/bookmarks", data=data_false
        )
        self.assertEqual(status_false, 201)
        self.assertIs(payload_false.get("is_favorite"), False)
        self.assertIsInstance(payload_false.get("is_favorite"), bool)

        # Direct database inspection
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_favorite FROM bookmarks WHERE id = ?",
                (payload_true["id"],),
            )
            row_true = cursor.fetchone()
            self.assertEqual(row_true[0], 1)

            cursor.execute(
                "SELECT is_favorite FROM bookmarks WHERE id = ?",
                (payload_false["id"],),
            )
            row_false = cursor.fetchone()
            self.assertEqual(row_false[0], 0)
        finally:
            conn.close()

    def test_create_bookmark_invalid_is_favorite(self) -> None:
        """Verifies POST /api/bookmarks rejects non-boolean is_favorite with 400 Bad Request."""
        invalid_values = [
            "true",
            "false",
            "1",
            "0",
            1,
            0,
            "yes",
            "no",
            None,
            [],
            [True],
            {},
            {"favorite": True},
        ]
        for val in invalid_values:
            with self.subTest(invalid_val=val):
                status, payload, _, _ = self.make_request(
                    "POST",
                    "/api/bookmarks",
                    data={
                        "title": "Invalid Fav Test",
                        "url": "https://example.com/invalid-fav",
                        "is_favorite": val,
                    },
                )
                self.assertEqual(status, 400)
                self.assertIsInstance(payload, dict)
                self.assertIn("error", payload)

    # 4. Create bookmark validation failures
    def test_create_bookmark_missing_or_invalid_title(self) -> None:
        """Verifies POST /api/bookmarks returns 400 when title is missing, empty, or non-string."""
        # Missing title
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"url": "https://example.com"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Empty title
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"title": "", "url": "https://example.com"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Whitespace-only title
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "   \t\n  ", "url": "https://example.com"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Non-string title
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"title": 12345, "url": "https://example.com"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_create_bookmark_missing_or_invalid_url(self) -> None:
        """Verifies POST /api/bookmarks returns 400 when url is missing, empty, invalid scheme, or non-string."""
        # Missing url
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"title": "Test Title"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Empty url
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"title": "Test Title", "url": ""}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Whitespace-only url
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"title": "Test Title", "url": "   "}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Non-string url
        status, payload, _, _ = self.make_request(
            "POST", "/api/bookmarks", data={"title": "Test Title", "url": ["https://example.com"]}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Invalid URL scheme (ftp instead of http/https)
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Test Title", "url": "ftp://example.com/file"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # URL without host
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Test Title", "url": "http://"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_create_bookmark_invalid_notes_or_payload(self) -> None:
        """Verifies POST /api/bookmarks returns 400 when notes is non-string or payload is malformed."""
        # Non-string notes
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Title", "url": "https://example.com", "notes": 999},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Missing body
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data=None,
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Empty body
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data="",
            headers={"Content-Length": "0"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # Malformed JSON syntax
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data="{invalid_json:",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        # JSON array instead of dictionary object
        status, payload, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data=[{"title": "Title", "url": "https://example.com"}],
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    # 5. Search filtering
    def test_search_filtering(self) -> None:
        """Verifies GET /api/bookmarks?q= matches title, url, or notes case-insensitively."""
        bm1 = {
            "title": "Python Language Reference",
            "url": "https://docs.python.org/3/",
            "notes": "Core stdlib and syntax",
        }
        bm2 = {
            "title": "SQLite Embedded Engine",
            "url": "https://www.sqlite.org/",
            "notes": "C-tree structured database",
        }
        bm3 = {
            "title": "MDN Web Standards",
            "url": "https://developer.mozilla.org/",
            "notes": "JavaScript and CSS documentation",
        }
        self.make_request("POST", "/api/bookmarks", data=bm1)
        self.make_request("POST", "/api/bookmarks", data=bm2)
        self.make_request("POST", "/api/bookmarks", data=bm3)

        # All bookmarks when q is omitted
        status, all_bms, _, _ = self.make_request("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertEqual(len(all_bms), 3)

        # Search matching title (case-insensitive)
        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=pYtHoN")
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Python Language Reference")

        # Search matching URL
        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=sqlite.org")
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "SQLite Embedded Engine")

        # Search matching notes
        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=documentation")
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "MDN Web Standards")

        # Search matching multiple entries
        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=reference")
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 1)

        # Non-matching search query returns empty array
        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=RustLangNonExistent")
        self.assertEqual(status, 200)
        self.assertEqual(results, [])

        # Empty or whitespace search query returns all
        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=")
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 3)

        status, results, _, _ = self.make_request("GET", "/api/bookmarks?q=%20%20")
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 3)

    # 6. Retrieve single bookmark by ID
    def test_get_bookmark_by_id(self) -> None:
        """Verifies GET /api/bookmarks/<id> returns 200, 404 for missing, and 400 for invalid ID."""
        _, created, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Test", "url": "https://test.com", "notes": "Notes"},
        )
        bm_id = created["id"]

        # Valid ID
        status, bm, _, _ = self.make_request("GET", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status, 200)
        self.assertEqual(bm["id"], bm_id)
        self.assertEqual(bm["title"], "Test")
        self.assertIs(bm["is_favorite"], False)

        # Non-existent ID
        status, err, _, _ = self.make_request("GET", "/api/bookmarks/99999")
        self.assertEqual(status, 404)
        self.assertIn("error", err)

        # Non-integer ID
        status, err, _, _ = self.make_request("GET", "/api/bookmarks/invalid_id")
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Non-positive integer ID
        status, err, _, _ = self.make_request("GET", "/api/bookmarks/-5")
        self.assertEqual(status, 400)
        self.assertIn("error", err)

    # 7. Update bookmark (PATCH) and Favorite Toggling
    def test_patch_toggle_is_favorite(self) -> None:
        """Verifies PATCH /api/bookmarks/<id> toggles is_favorite to true and false with boolean serialization."""
        # 1. Create a bookmark (default is_favorite=False)
        _, created, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={
                "title": "Toggle Favorite Test",
                "url": "https://example.com/toggle",
                "notes": "Testing toggle",
            },
        )
        bm_id = created["id"]
        self.assertIs(created["is_favorite"], False)
        created_at = created["created_at"]
        orig_updated_at = created["updated_at"]

        # Sleep briefly to ensure updated_at timestamp advances
        time.sleep(1.05)

        # 2. Toggle to True
        status, updated, _, _ = self.make_request(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data={"is_favorite": True},
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(updated, dict)
        self.assertEqual(updated["id"], bm_id)
        self.assertEqual(updated["title"], "Toggle Favorite Test")
        self.assertEqual(updated["url"], "https://example.com/toggle")
        self.assertEqual(updated["notes"], "Testing toggle")
        self.assertIs(updated["is_favorite"], True)
        self.assertIsInstance(updated["is_favorite"], bool)
        self.assertEqual(updated["created_at"], created_at)
        self.assertNotEqual(updated["updated_at"], orig_updated_at)

        # Verify via GET /api/bookmarks/<id>
        status_get, bm_get, _, _ = self.make_request("GET", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status_get, 200)
        self.assertIs(bm_get["is_favorite"], True)

        # Direct database inspection
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT is_favorite FROM bookmarks WHERE id = ?", (bm_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1)
        finally:
            conn.close()

        # Sleep briefly
        time.sleep(1.05)
        second_updated_at = updated["updated_at"]

        # 3. Toggle back to False
        status, updated2, _, _ = self.make_request(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data={"is_favorite": False},
        )
        self.assertEqual(status, 200)
        self.assertIs(updated2["is_favorite"], False)
        self.assertIsInstance(updated2["is_favorite"], bool)
        self.assertNotEqual(updated2["updated_at"], second_updated_at)

        # Verify via GET /api/bookmarks/<id>
        status_get2, bm_get2, _, _ = self.make_request("GET", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status_get2, 200)
        self.assertIs(bm_get2["is_favorite"], False)

        # Direct database inspection
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT is_favorite FROM bookmarks WHERE id = ?", (bm_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 0)
        finally:
            conn.close()

        # 4. Toggle to True alongside notes update
        status, updated3, _, _ = self.make_request(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data={"notes": "Updated notes with favorite", "is_favorite": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated3["notes"], "Updated notes with favorite")
        self.assertIs(updated3["is_favorite"], True)

    def test_patch_invalid_is_favorite(self) -> None:
        """Verifies PATCH /api/bookmarks/<id> rejects non-boolean is_favorite with 400 Bad Request."""
        _, created, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Patch Invalid Fav", "url": "https://example.com/patch-fav"},
        )
        bm_id = created["id"]

        invalid_values = [
            "true",
            "false",
            "1",
            "0",
            1,
            0,
            "yes",
            "no",
            None,
            [],
            [True],
            {},
            {"is_favorite": True},
        ]
        for val in invalid_values:
            with self.subTest(invalid_val=val):
                status, payload, _, _ = self.make_request(
                    "PATCH",
                    f"/api/bookmarks/{bm_id}",
                    data={"is_favorite": val},
                )
                self.assertEqual(status, 400)
                self.assertIsInstance(payload, dict)
                self.assertIn("error", payload)

        # Verify bookmark still has original is_favorite=False
        status_get, bm_get, _, _ = self.make_request("GET", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status_get, 200)
        self.assertIs(bm_get["is_favorite"], False)

    # 8. Favorite filtering
    def test_get_bookmarks_favorites_filter(self) -> None:
        """Verifies GET /api/bookmarks?favorites=true returns only favorite bookmarks and supports q combination."""
        # Create 4 bookmarks: 2 favorites, 2 non-favorites
        bm1_data = {
            "title": "Python Docs",
            "url": "https://docs.python.org/3/",
            "notes": "Core stdlib reference",
            "is_favorite": False,
        }
        bm2_data = {
            "title": "FastAPI Web Framework",
            "url": "https://fastapi.tiangolo.com/",
            "notes": "Modern high-performance Python framework",
            "is_favorite": True,
        }
        bm3_data = {
            "title": "SQLite Tutorial",
            "url": "https://www.sqlite.org/",
            "notes": "Embedded SQL engine docs",
            "is_favorite": False,
        }
        bm4_data = {
            "title": "Python Packaging Guide",
            "url": "https://packaging.python.org/",
            "notes": "PyPI and packaging tools",
            "is_favorite": True,
        }

        _, b1, _, _ = self.make_request("POST", "/api/bookmarks", data=bm1_data)
        _, b2, _, _ = self.make_request("POST", "/api/bookmarks", data=bm2_data)
        _, b3, _, _ = self.make_request("POST", "/api/bookmarks", data=bm3_data)
        _, b4, _, _ = self.make_request("POST", "/api/bookmarks", data=bm4_data)

        # 1. Unfiltered request returns all 4 bookmarks
        status, all_bms, _, _ = self.make_request("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertEqual(len(all_bms), 4)

        # 2. Filter favorites=true returns only b2 and b4
        status, favs, _, _ = self.make_request("GET", "/api/bookmarks?favorites=true")
        self.assertEqual(status, 200)
        self.assertIsInstance(favs, list)
        self.assertEqual(len(favs), 2)
        fav_ids = [b["id"] for b in favs]
        self.assertEqual(fav_ids, [b2["id"], b4["id"]])
        for b in favs:
            self.assertIs(b["is_favorite"], True)

        # 3. Case-insensitivity: favorites=True and favorites=TRUE
        status_cap, favs_cap, _, _ = self.make_request("GET", "/api/bookmarks?favorites=True")
        self.assertEqual(status_cap, 200)
        self.assertEqual([b["id"] for b in favs_cap], [b2["id"], b4["id"]])

        status_upper, favs_upper, _, _ = self.make_request("GET", "/api/bookmarks?favorites=TRUE")
        self.assertEqual(status_upper, 200)
        self.assertEqual([b["id"] for b in favs_upper], [b2["id"], b4["id"]])

        # 4. favorites=false returns all bookmarks (no favorite filter)
        status_false, bms_false, _, _ = self.make_request("GET", "/api/bookmarks?favorites=false")
        self.assertEqual(status_false, 200)
        self.assertEqual(len(bms_false), 4)

        # 5. favorites= (empty) returns all bookmarks
        status_empty, bms_empty, _, _ = self.make_request("GET", "/api/bookmarks?favorites=")
        self.assertEqual(status_empty, 200)
        self.assertEqual(len(bms_empty), 4)

        # 6. Combining favorites=true with search query q
        # Search for "Python": matches b1 (non-fav), b2 (notes contain Python), b4 (title contains Python)
        # With favorites=true: should only return b2 and b4 (excluding b1 because not favorite)
        status_combo, combo_res, _, _ = self.make_request(
            "GET", "/api/bookmarks?favorites=true&q=Python"
        )
        self.assertEqual(status_combo, 200)
        self.assertEqual(len(combo_res), 2)
        self.assertEqual([b["id"] for b in combo_res], [b2["id"], b4["id"]])

        # Search for "FastAPI" with favorites=true: matches only b2
        status_fa, fa_res, _, _ = self.make_request(
            "GET", "/api/bookmarks?favorites=true&q=FastAPI"
        )
        self.assertEqual(status_fa, 200)
        self.assertEqual(len(fa_res), 1)
        self.assertEqual(fa_res[0]["id"], b2["id"])

        # Search for "SQLite" with favorites=true: b3 matches SQLite but is NOT favorite -> empty list []
        status_sql, sql_res, _, _ = self.make_request(
            "GET", "/api/bookmarks?favorites=true&q=SQLite"
        )
        self.assertEqual(status_sql, 200)
        self.assertEqual(sql_res, [])

        # Search for "SQLite" without favorites: returns b3
        status_sql_all, sql_all_res, _, _ = self.make_request(
            "GET", "/api/bookmarks?q=SQLite"
        )
        self.assertEqual(status_sql_all, 200)
        self.assertEqual(len(sql_all_res), 1)
        self.assertEqual(sql_all_res[0]["id"], b3["id"])

    def test_update_bookmark_valid(self) -> None:
        """Verifies PATCH /api/bookmarks/<id> updates fields and refreshes updated_at timestamp."""
        _, created, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={
                "title": "Original Title",
                "url": "https://original.com",
                "notes": "Original Notes",
            },
        )
        bm_id = created["id"]
        created_at = created["created_at"]
        orig_updated_at = created["updated_at"]

        # Sleep briefly to ensure updated_at timestamp advances past the second boundary
        time.sleep(1.05)

        # Update notes only
        status, updated, _, _ = self.make_request(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data={"notes": "Updated Notes Content"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["id"], bm_id)
        self.assertEqual(updated["title"], "Original Title")
        self.assertEqual(updated["url"], "https://original.com")
        self.assertEqual(updated["notes"], "Updated Notes Content")
        self.assertEqual(updated["created_at"], created_at)
        self.assertNotEqual(updated["updated_at"], orig_updated_at)

        # Update title and url
        status, updated2, _, _ = self.make_request(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data={
                "title": "New Title",
                "url": "https://new.example.com/docs",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated2["title"], "New Title")
        self.assertEqual(updated2["url"], "https://new.example.com/docs")
        self.assertEqual(updated2["notes"], "Updated Notes Content")

    def test_update_bookmark_validation_errors(self) -> None:
        """Verifies PATCH /api/bookmarks/<id> rejects invalid payloads and non-existent IDs."""
        _, created, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Valid", "url": "https://valid.com"},
        )
        bm_id = created["id"]

        # Non-existent bookmark
        status, err, _, _ = self.make_request(
            "PATCH", "/api/bookmarks/99999", data={"notes": "Ghost notes"}
        )
        self.assertEqual(status, 404)
        self.assertIn("error", err)

        # Non-integer ID
        status, err, _, _ = self.make_request(
            "PATCH", "/api/bookmarks/abc", data={"title": "New"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Empty update payload
        status, err, _, _ = self.make_request(
            "PATCH", f"/api/bookmarks/{bm_id}", data={}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Payload with no updatable fields
        status, err, _, _ = self.make_request(
            "PATCH", f"/api/bookmarks/{bm_id}", data={"unknown_key": "val"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Empty / whitespace title
        status, err, _, _ = self.make_request(
            "PATCH", f"/api/bookmarks/{bm_id}", data={"title": "   "}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Invalid URL
        status, err, _, _ = self.make_request(
            "PATCH", f"/api/bookmarks/{bm_id}", data={"url": "not_a_valid_url"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Non-string notes
        status, err, _, _ = self.make_request(
            "PATCH", f"/api/bookmarks/{bm_id}", data={"notes": 12345}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Non-boolean is_favorite
        status, err, _, _ = self.make_request(
            "PATCH", f"/api/bookmarks/{bm_id}", data={"is_favorite": "not_a_boolean"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        # Malformed JSON
        status, err, _, _ = self.make_request(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data="{malformed_json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", err)

    # 9. Delete bookmark
    def test_delete_bookmark_success_and_subsequent_404(self) -> None:
        """Verifies DELETE /api/bookmarks/<id> deletes a bookmark and subsequent calls return 404."""
        _, created, _, _ = self.make_request(
            "POST",
            "/api/bookmarks",
            data={"title": "Delete Me", "url": "https://deleteme.com"},
        )
        bm_id = created["id"]

        # Successful deletion
        status, payload, _, _ = self.make_request(
            "DELETE", f"/api/bookmarks/{bm_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("status"), "deleted")
        self.assertEqual(payload.get("id"), bm_id)

        # Subsequent DELETE on same ID returns 404
        status, err, _, _ = self.make_request(
            "DELETE", f"/api/bookmarks/{bm_id}"
        )
        self.assertEqual(status, 404)
        self.assertIn("error", err)

        # Subsequent GET on same ID returns 404
        status, err, _, _ = self.make_request("GET", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status, 404)

        # Verify bookmark is not in list
        status, bms, _, _ = self.make_request("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertNotIn(bm_id, [b["id"] for b in bms])

    def test_delete_bookmark_validation_errors(self) -> None:
        """Verifies DELETE /api/bookmarks/<id> returns 404 for missing ID and 400 for invalid ID."""
        # Non-existent ID
        status, err, _, _ = self.make_request("DELETE", "/api/bookmarks/99999")
        self.assertEqual(status, 404)
        self.assertIn("error", err)

        # Non-integer ID
        status, err, _, _ = self.make_request("DELETE", "/api/bookmarks/abc")
        self.assertEqual(status, 400)
        self.assertIn("error", err)

    # 10. Static file delivery
    def test_static_file_serving(self) -> None:
        """Verifies static assets (HTML, CSS, JS) are served with correct MIME types."""
        # Root path /
        status, _, headers, body = self.make_request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("MiniLinks", body.decode("utf-8"))

        # Explicit /index.html
        status, _, headers, body = self.make_request("GET", "/index.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("<!DOCTYPE html>", body.decode("utf-8"))

        # /style.css
        status, _, headers, body = self.make_request("GET", "/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("content-type", ""))
        self.assertGreater(len(body), 0)

        # /app.js
        status, _, headers, body = self.make_request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript", headers.get("content-type", ""))
        self.assertGreater(len(body), 0)

        # Non-existent static file returns 404
        status, _, _, _ = self.make_request("GET", "/missing_asset.txt")
        self.assertEqual(status, 404)

    # 11. Directory traversal protection
    def test_directory_traversal_protection(self) -> None:
        """Verifies path traversal attempts are rejected with 403 or 404."""
        # Raw .. traversal
        status1, _, _ = self.raw_request("GET", "/../app/server.py")
        self.assertIn(status1, (403, 404))

        # URL-encoded traversal (%2e%2e)
        status2, _, _ = self.raw_request("GET", "/%2e%2e/app/database.py")
        self.assertIn(status2, (403, 404))

        # Traversal with encoded slash (%2f)
        status3, _, _ = self.raw_request("GET", "/..%2fstyle.css")
        self.assertIn(status3, (403, 404))

        # Deep traversal
        status4, _, _ = self.raw_request("GET", "/nested/../../etc/passwd")
        self.assertIn(status4, (403, 404))

    # 12. CORS and unsupported endpoints
    def test_cors_options(self) -> None:
        """Verifies OPTIONS preflight request returns 204 with CORS headers."""
        status, _, headers, _ = self.make_request("OPTIONS", "/api/bookmarks")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertIn("GET", headers.get("access-control-allow-methods", ""))
        self.assertIn("POST", headers.get("access-control-allow-methods", ""))

    def test_unknown_endpoints(self) -> None:
        """Verifies unknown API endpoints return 404 JSON error."""
        status, err, _, _ = self.make_request("GET", "/api/unknown_route")
        self.assertEqual(status, 404)
        self.assertIn("error", err)

        status, err, _, _ = self.make_request("POST", "/api/unknown_route", data={})
        self.assertEqual(status, 404)
        self.assertIn("error", err)

    # 13. Concurrency verification using threading
    def test_concurrent_api_requests(self) -> None:
        """Verifies multiple threads can query the API concurrently without deadlocks."""
        errors: list = []

        def worker() -> None:
            try:
                for _ in range(5):
                    status, payload, _, _ = self.make_request("GET", "/health")
                    if status != 200 or payload.get("status") != "ok":
                        errors.append(f"Unexpected health check response: {status}, {payload}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent request errors: {errors}")


if __name__ == "__main__":
    unittest.main()
