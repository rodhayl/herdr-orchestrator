"""
MiniLinks REST API and Static Asset Delivery Test Suite.

Validates all HTTP API endpoints against a live server running on an ephemeral port
with an isolated temporary SQLite database, strictly using the Python standard library.
"""

import http.client
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
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


class TestMiniLinksAPI(unittest.TestCase):
    """Integration test suite covering MiniLinks REST API and static asset delivery."""

    def setUp(self):
        """Set up an ephemeral SQLite database and start the background HTTPServer."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_api.db")
        self.server = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.host = getattr(self.server, "server_name", None) or self.server.server_address[0]
        if self.host == "0.0.0.0":
            self.host = "127.0.0.1"
        self.port = getattr(self.server, "server_port", None) or self.server.server_address[1]
        self.base_url = f"http://{self.host}:{self.port}"

    def tearDown(self):
        """Cleanly shut down the server and remove temporary directory."""
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def _request(self, method: str, path: str, data=None, headers=None):
        """Helper to send an HTTP request using urllib.request and return (status, headers, body_bytes)."""
        url = f"{self.base_url}{path}"
        req_headers = headers.copy() if headers else {}
        body = None

        if data is not None:
            if isinstance(data, (dict, list)):
                body = json.dumps(data).encode("utf-8")
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/json"
            elif isinstance(data, str):
                body = data.encode("utf-8")
            elif isinstance(data, bytes):
                body = data

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def _request_json(self, method: str, path: str, data=None, headers=None):
        """Helper to send request and decode JSON response if available."""
        status, resp_headers, body = self._request(method, path, data=data, headers=headers)
        json_data = None
        if body:
            try:
                json_data = json.loads(body.decode("utf-8"))
            except Exception:
                json_data = None
        return status, json_data, resp_headers

    # 1. Health check
    def test_health_check(self):
        """GET /health must return 200 OK and {"status": "ok"}."""
        status, data, _ = self._request_json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("status"), "ok")

    # 2. Initial bookmark listing
    def test_initial_bookmarks_empty(self):
        """GET /api/bookmarks on clean DB must return 200 OK and empty array []."""
        status, data, _ = self._request_json("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 0)

    # 3. Create bookmark valid
    def test_create_bookmark_valid(self):
        """POST /api/bookmarks creates bookmark and returns 201 Created with full object."""
        payload = {
            "title": "MDN Web Docs",
            "url": "https://developer.mozilla.org/",
            "notes": "Web standards and guides",
        }
        status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
        self.assertEqual(status, 201)
        self.assertIsInstance(data, dict)
        self.assertIn("id", data)
        self.assertIsInstance(data["id"], int)
        self.assertGreater(data["id"], 0)
        self.assertEqual(data["title"], "MDN Web Docs")
        self.assertEqual(data["url"], "https://developer.mozilla.org/")
        self.assertEqual(data["notes"], "Web standards and guides")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertTrue(len(data["created_at"]) > 0)
        self.assertTrue(len(data["updated_at"]) > 0)

    def test_create_bookmark_default_notes(self):
        """POST /api/bookmarks without notes defaults notes to empty string."""
        payload = {
            "title": "Python Docs",
            "url": "https://docs.python.org/3/",
        }
        status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
        self.assertEqual(status, 201)
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("notes"), "")
        self.assertEqual(data["title"], "Python Docs")
        self.assertEqual(data["url"], "https://docs.python.org/3/")

    def test_create_bookmark_whitespace_stripping(self):
        """POST /api/bookmarks with whitespace in title/url strips them properly."""
        payload = {
            "title": "  Python Documentation  ",
            "url": "  https://docs.python.org/3/  ",
            "notes": "  Some notes  ",
        }
        status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
        self.assertEqual(status, 201)
        self.assertEqual(data["title"], "Python Documentation")
        self.assertEqual(data["url"], "https://docs.python.org/3/")

    # 4. Create bookmark validation errors
    def test_create_bookmark_missing_title(self):
        """POST /api/bookmarks missing title must return 400 Bad Request."""
        payload = {"url": "https://docs.python.org/"}
        status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_create_bookmark_empty_title(self):
        """POST /api/bookmarks with empty or whitespace-only title must return 400."""
        for empty_val in ("", "   ", "\t\n"):
            payload = {"title": empty_val, "url": "https://docs.python.org/"}
            status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
            self.assertEqual(status, 400, f"Expected 400 for title={empty_val!r}")
            self.assertIn("error", data)

    def test_create_bookmark_missing_url(self):
        """POST /api/bookmarks missing url must return 400 Bad Request."""
        payload = {"title": "Python Docs"}
        status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_create_bookmark_empty_url(self):
        """POST /api/bookmarks with empty or whitespace-only url must return 400."""
        for empty_val in ("", "   ", "\t\n"):
            payload = {"title": "Python Docs", "url": empty_val}
            status, data, _ = self._request_json("POST", "/api/bookmarks", data=payload)
            self.assertEqual(status, 400, f"Expected 400 for url={empty_val!r}")
            self.assertIn("error", data)

    def test_create_bookmark_non_string_types(self):
        """POST /api/bookmarks with non-string fields must return 400."""
        invalid_payloads = [
            {"title": 12345, "url": "https://example.com"},
            {"title": "Valid", "url": 12345},
            {"title": "Valid", "url": "https://example.com", "notes": 12345},
            {"title": None, "url": "https://example.com"},
            {"title": "Valid", "url": None},
        ]
        for p in invalid_payloads:
            status, data, _ = self._request_json("POST", "/api/bookmarks", data=p)
            self.assertEqual(status, 400, f"Expected 400 for payload={p}")
            self.assertIn("error", data)

    def test_create_bookmark_malformed_json(self):
        """POST /api/bookmarks with malformed JSON body must return 400."""
        status, data, _ = self._request_json(
            "POST",
            "/api/bookmarks",
            data="{invalid_json: true}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_create_bookmark_empty_body(self):
        """POST /api/bookmarks with empty body must return 400."""
        status, data, _ = self._request_json(
            "POST",
            "/api/bookmarks",
            data="",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # 5. Search filtering
    def test_search_filtering(self):
        """GET /api/bookmarks?q=<term> filters by title, url, or notes (case-insensitive)."""
        # Create 3 bookmarks
        self._request_json("POST", "/api/bookmarks", data={
            "title": "Python Documentation",
            "url": "https://docs.python.org/3/",
            "notes": "Official reference guide",
        })
        self._request_json("POST", "/api/bookmarks", data={
            "title": "SQLite Tutorial",
            "url": "https://www.sqlite.org/",
            "notes": "Lightweight embedded database engine",
        })
        self._request_json("POST", "/api/bookmarks", data={
            "title": "MDN Web Docs",
            "url": "https://developer.mozilla.org/",
            "notes": "HTML, CSS, and JavaScript standards",
        })

        # Match title
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=python")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Python Documentation")

        # Case insensitivity
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=pYtHoN")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Python Documentation")

        # Match url
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=sqlite.org")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "SQLite Tutorial")

        # Match notes
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=embedded")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "SQLite Tutorial")

        # Match multiple across title / notes
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=docs")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 2)  # Python Docs and MDN Web Docs

        # Non-matching query
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=nonexistenttermXYZ")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 0)

        # Empty q returns all
        status, data, _ = self._request_json("GET", "/api/bookmarks?q=")
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 3)

    # 6. Update bookmark (PATCH)
    def test_patch_bookmark_fields(self):
        """PATCH /api/bookmarks/<id> updates title, url, notes individually or together."""
        # Create bookmark
        _, created, _ = self._request_json("POST", "/api/bookmarks", data={
            "title": "Initial Title",
            "url": "https://initial.org/",
            "notes": "Initial Notes",
        })
        bm_id = created["id"]
        original_created_at = created["created_at"]

        # Small sleep to allow updated_at to increment if time precision is coarse
        time.sleep(0.05)

        # Update title only
        status, data, _ = self._request_json("PATCH", f"/api/bookmarks/{bm_id}", data={
            "title": "Updated Title",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "Updated Title")
        self.assertEqual(data["url"], "https://initial.org/")
        self.assertEqual(data["notes"], "Initial Notes")
        self.assertEqual(data["created_at"], original_created_at)

        # Update url and notes together
        status, data, _ = self._request_json("PATCH", f"/api/bookmarks/{bm_id}", data={
            "url": "https://updated.org/",
            "notes": "Updated Notes",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "Updated Title")
        self.assertEqual(data["url"], "https://updated.org/")
        self.assertEqual(data["notes"], "Updated Notes")

        # Verify through GET
        status, all_bms, _ = self._request_json("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertEqual(len(all_bms), 1)
        self.assertEqual(all_bms[0]["title"], "Updated Title")
        self.assertEqual(all_bms[0]["url"], "https://updated.org/")
        self.assertEqual(all_bms[0]["notes"], "Updated Notes")

    # 7. Update errors (404 and 400)
    def test_patch_bookmark_not_found(self):
        """PATCH /api/bookmarks/<id> with non-existent ID returns 404 Not Found."""
        status, data, _ = self._request_json("PATCH", "/api/bookmarks/99999", data={
            "title": "Ghost",
        })
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_patch_bookmark_invalid_id(self):
        """PATCH /api/bookmarks/<id> with non-integer ID returns 400 Bad Request."""
        status, data, _ = self._request_json("PATCH", "/api/bookmarks/notanint", data={
            "title": "Invalid ID",
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_patch_bookmark_empty_payload(self):
        """PATCH /api/bookmarks/<id> with empty payload returns 400 Bad Request."""
        _, created, _ = self._request_json("POST", "/api/bookmarks", data={
            "title": "Some Title",
            "url": "https://example.com/",
        })
        bm_id = created["id"]

        status, data, _ = self._request_json("PATCH", f"/api/bookmarks/{bm_id}", data={})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_patch_bookmark_invalid_field_values(self):
        """PATCH /api/bookmarks/<id> with empty or non-string values returns 400 Bad Request."""
        _, created, _ = self._request_json("POST", "/api/bookmarks", data={
            "title": "Some Title",
            "url": "https://example.com/",
        })
        bm_id = created["id"]

        invalid_patches = [
            {"title": ""},
            {"title": "   "},
            {"url": ""},
            {"url": "   "},
            {"title": 123},
            {"url": 123},
            {"notes": 123},
            {"title": None},
            {"url": None},
        ]
        for p in invalid_patches:
            status, data, _ = self._request_json("PATCH", f"/api/bookmarks/{bm_id}", data=p)
            self.assertEqual(status, 400, f"Expected 400 for PATCH payload={p}")
            self.assertIn("error", data)

    def test_patch_bookmark_malformed_json(self):
        """PATCH /api/bookmarks/<id> with malformed JSON returns 400 Bad Request."""
        _, created, _ = self._request_json("POST", "/api/bookmarks", data={
            "title": "Some Title",
            "url": "https://example.com/",
        })
        bm_id = created["id"]

        status, data, _ = self._request_json(
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            data="{not_valid_json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # 8. Delete bookmark
    def test_delete_bookmark_success(self):
        """DELETE /api/bookmarks/<id> returns 200 OK and deletes the record."""
        _, created, _ = self._request_json("POST", "/api/bookmarks", data={
            "title": "To Delete",
            "url": "https://example.com/delete",
        })
        bm_id = created["id"]

        status, data, _ = self._request_json("DELETE", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "deleted")
        self.assertEqual(data.get("id"), bm_id)

        # Verify listing is now empty
        status, all_bms, _ = self._request_json("GET", "/api/bookmarks")
        self.assertEqual(status, 200)
        self.assertEqual(len(all_bms), 0)

    def test_delete_bookmark_not_found(self):
        """DELETE /api/bookmarks/<id> with non-existent ID returns 404 Not Found."""
        status, data, _ = self._request_json("DELETE", "/api/bookmarks/99999")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_delete_bookmark_repeated_deletion(self):
        """Second DELETE on same ID returns 404 Not Found."""
        _, created, _ = self._request_json("POST", "/api/bookmarks", data={
            "title": "To Delete Twice",
            "url": "https://example.com/delete2",
        })
        bm_id = created["id"]

        # First deletion succeeds
        status, _, _ = self._request_json("DELETE", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status, 200)

        # Second deletion returns 404
        status, data, _ = self._request_json("DELETE", f"/api/bookmarks/{bm_id}")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_delete_bookmark_invalid_id(self):
        """DELETE /api/bookmarks/<id> with non-integer ID returns 400 Bad Request."""
        status, data, _ = self._request_json("DELETE", "/api/bookmarks/invalid_id")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # 9. Static file delivery
    def test_static_files_delivery(self):
        """Verifies delivery of index.html, style.css, and app.js with appropriate MIME types."""
        endpoints = [
            ("/", ("text/html",)),
            ("/index.html", ("text/html",)),
            ("/style.css", ("text/css",)),
            ("/app.js", ("application/javascript", "text/javascript")),
        ]
        for path, expected_content_types in endpoints:
            status, headers, body = self._request("GET", path)
            self.assertEqual(status, 200, f"Expected 200 for static path {path}")
            self.assertGreater(len(body), 0, f"Expected non-empty body for static path {path}")
            content_type = headers.get("Content-Type", "")
            matches = any(ct in content_type for ct in expected_content_types)
            self.assertTrue(
                matches,
                f"Expected one of {expected_content_types} in Content-Type: {content_type} for {path}",
            )

    def test_static_file_not_found(self):
        """GET for non-existent static file returns 404 Not Found."""
        status, _, _ = self._request("GET", "/non_existent_asset_xyz.txt")
        self.assertEqual(status, 404)

    # 10. Directory traversal protection
    def test_directory_traversal_protection(self):
        """Requests with path traversal sequences must be rejected with 403 or 404."""
        traversal_paths = [
            "/../SPEC.md",
            "/..%2F..%2FSPEC.md",
            "/..%2f..%2fetc%2fpasswd",
            "/web/../../SPEC.md",
            "/%2e%2e/%2e%2e/SPEC.md",
            "/....//SPEC.md",
        ]
        for path in traversal_paths:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                self.assertIn(
                    status,
                    (400, 403, 404),
                    f"Directory traversal path {path} returned unexpected status {status}",
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
