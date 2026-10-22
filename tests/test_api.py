"""
tests/test_api.py
Comprehensive unit and integration test suite for MiniBoard REST API endpoints
and static file serving, adhering strictly to the Python 3 standard library.
"""

import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from typing import Any, Optional

# Ensure repository root is on sys.path for direct imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.server import create_server


class ApiResponse:
    """Convenience wrapper around HTTP response data for assertions."""

    def __init__(self, status: int, body_bytes: bytes, headers: Any):
        self.status = status
        self.body_bytes = body_bytes
        self.headers = headers

    @property
    def text(self) -> str:
        return self.body_bytes.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text)


class TestApiEndpoints(unittest.TestCase):
    """Integration test suite covering all REST API endpoints and static file routes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_api.db")
        self.server, self.thread = create_server(host="127.0.0.1", port=0, db_path=self.db_path)
        self.port = self.server.server_port
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        try:
            if hasattr(self, "server") and self.server is not None:
                self.server.shutdown()
                self.server.server_close()
            if hasattr(self, "thread") and self.thread is not None:
                self.thread.join(timeout=5.0)
        finally:
            if hasattr(self, "temp_dir") and self.temp_dir is not None:
                self.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        data: Any = None,
        headers: Optional[dict] = None,
    ) -> ApiResponse:
        """Sends an HTTP request using urllib.request and returns an ApiResponse."""
        url = f"{self.base_url}{path}"
        req_headers = {}
        if headers:
            req_headers.update(headers)
        body_bytes = None
        if data is not None:
            if isinstance(data, (dict, list)):
                body_bytes = json.dumps(data).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json; charset=utf-8")
            elif isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data

        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return ApiResponse(resp.status, resp.read(), resp.headers)
        except urllib.error.HTTPError as e:
            return ApiResponse(e.code, e.read(), e.headers)

    def get(self, path: str, headers: Optional[dict] = None) -> ApiResponse:
        return self.request("GET", path, headers=headers)

    def post(self, path: str, data: Any = None, headers: Optional[dict] = None) -> ApiResponse:
        return self.request("POST", path, data=data, headers=headers)

    def patch(self, path: str, data: Any = None, headers: Optional[dict] = None) -> ApiResponse:
        return self.request("PATCH", path, data=data, headers=headers)

    def delete(self, path: str, headers: Optional[dict] = None) -> ApiResponse:
        return self.request("DELETE", path, headers=headers)

    def options(self, path: str, headers: Optional[dict] = None) -> ApiResponse:
        return self.request("OPTIONS", path, headers=headers)

    # -------------------------------------------------------------------------
    # 1. Health Endpoint Tests
    # -------------------------------------------------------------------------

    def test_health_check_returns_ok(self):
        """GET /health must return HTTP 200 with JSON payload {'status': 'ok'}."""
        res = self.get("/health")
        self.assertEqual(res.status, 200)
        self.assertIn("application/json", res.headers.get("Content-Type", ""))
        self.assertEqual(res.json(), {"status": "ok"})

    # -------------------------------------------------------------------------
    # 2. Initial Task Listing Tests
    # -------------------------------------------------------------------------

    def test_get_tasks_initial_empty_list(self):
        """GET /api/tasks must return HTTP 200 and an empty JSON array [] initially."""
        res = self.get("/api/tasks")
        self.assertEqual(res.status, 200)
        self.assertIn("application/json", res.headers.get("Content-Type", ""))
        self.assertEqual(res.json(), [])

    # -------------------------------------------------------------------------
    # 3. Create Task (POST /api/tasks) Tests
    # -------------------------------------------------------------------------

    def test_create_task_with_default_status(self):
        """POST /api/tasks without status must default to 'TODO'."""
        res = self.post("/api/tasks", {"title": "Task with default status"})
        self.assertEqual(res.status, 201)
        self.assertIn("application/json", res.headers.get("Content-Type", ""))
        data = res.json()
        self.assertIsInstance(data["id"], int)
        self.assertGreater(data["id"], 0)
        self.assertEqual(data["title"], "Task with default status")
        self.assertEqual(data["status"], "TODO")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertTrue(data["created_at"])
        self.assertTrue(data["updated_at"])

    def test_create_task_with_explicit_valid_statuses(self):
        """POST /api/tasks with explicit 'TODO', 'DOING', and 'DONE' statuses."""
        for status in ("TODO", "DOING", "DONE"):
            res = self.post("/api/tasks", {"title": f"Task in {status}", "status": status})
            self.assertEqual(res.status, 201)
            data = res.json()
            self.assertEqual(data["status"], status)
            self.assertEqual(data["title"], f"Task in {status}")

    def test_create_task_trims_whitespace(self):
        """POST /api/tasks trims leading and trailing whitespace from title."""
        res = self.post("/api/tasks", {"title": "   Whitespace Title   "})
        self.assertEqual(res.status, 201)
        data = res.json()
        self.assertEqual(data["title"], "Whitespace Title")

    def test_create_task_validation_missing_body(self):
        """POST /api/tasks without body or content-length must fail with 400 Bad Request."""
        res = self.post("/api/tasks", None)
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

    def test_create_task_validation_malformed_json(self):
        """POST /api/tasks with invalid JSON syntax must return 400 Bad Request."""
        res = self.post(
            "/api/tasks",
            data=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

    def test_create_task_validation_missing_title(self):
        """POST /api/tasks without 'title' field must return 400 Bad Request."""
        res = self.post("/api/tasks", {"status": "TODO"})
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

    def test_create_task_validation_empty_or_whitespace_title(self):
        """POST /api/tasks with empty or whitespace-only title must return 400 Bad Request."""
        for invalid_title in ("", "   ", "\t\n"):
            res = self.post("/api/tasks", {"title": invalid_title})
            self.assertEqual(res.status, 400, f"Expected 400 for title={invalid_title!r}")
            self.assertIn("error", res.json())

    def test_create_task_validation_non_string_title(self):
        """POST /api/tasks with non-string title must return 400 Bad Request."""
        for invalid_title in (12345, None, True, ["title"]):
            res = self.post("/api/tasks", {"title": invalid_title})
            self.assertEqual(res.status, 400, f"Expected 400 for title={invalid_title!r}")
            self.assertIn("error", res.json())

    def test_create_task_validation_invalid_status(self):
        """POST /api/tasks with status not in ('TODO', 'DOING', 'DONE') returns 400."""
        for invalid_status in ("ARCHIVED", "PROGRESS", "todo", "done", 123):
            res = self.post("/api/tasks", {"title": "Valid Title", "status": invalid_status})
            self.assertEqual(res.status, 400, f"Expected 400 for status={invalid_status!r}")
            self.assertIn("error", res.json())

    # -------------------------------------------------------------------------
    # 4. Task Listing After Creation (GET /api/tasks)
    # -------------------------------------------------------------------------

    def test_get_tasks_ordering_and_content(self):
        """GET /api/tasks returns all tasks ordered by id ASC."""
        task1 = self.post("/api/tasks", {"title": "First Task", "status": "TODO"}).json()
        task2 = self.post("/api/tasks", {"title": "Second Task", "status": "DOING"}).json()
        task3 = self.post("/api/tasks", {"title": "Third Task", "status": "DONE"}).json()

        res = self.get("/api/tasks")
        self.assertEqual(res.status, 200)
        tasks = res.json()
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0]["id"], task1["id"])
        self.assertEqual(tasks[0]["title"], "First Task")
        self.assertEqual(tasks[0]["status"], "TODO")

        self.assertEqual(tasks[1]["id"], task2["id"])
        self.assertEqual(tasks[1]["title"], "Second Task")
        self.assertEqual(tasks[1]["status"], "DOING")

        self.assertEqual(tasks[2]["id"], task3["id"])
        self.assertEqual(tasks[2]["title"], "Third Task")
        self.assertEqual(tasks[2]["status"], "DONE")

    # -------------------------------------------------------------------------
    # 5. Update Task (PATCH /api/tasks/<id>) Tests
    # -------------------------------------------------------------------------

    def test_patch_task_status_transition(self):
        """PATCH /api/tasks/<id> updates status while preserving title."""
        created = self.post("/api/tasks", {"title": "Status Update Task", "status": "TODO"}).json()
        task_id = created["id"]

        res = self.patch(f"/api/tasks/{task_id}", {"status": "DOING"})
        self.assertEqual(res.status, 200)
        data = res.json()
        self.assertEqual(data["id"], task_id)
        self.assertEqual(data["status"], "DOING")
        self.assertEqual(data["title"], "Status Update Task")
        self.assertIn("updated_at", data)

        res2 = self.patch(f"/api/tasks/{task_id}", {"status": "DONE"})
        self.assertEqual(res2.status, 200)
        self.assertEqual(res2.json()["status"], "DONE")

    def test_patch_task_title(self):
        """PATCH /api/tasks/<id> updates title while preserving status."""
        created = self.post("/api/tasks", {"title": "Original Title", "status": "DOING"}).json()
        task_id = created["id"]

        res = self.patch(f"/api/tasks/{task_id}", {"title": "Updated Title"})
        self.assertEqual(res.status, 200)
        data = res.json()
        self.assertEqual(data["id"], task_id)
        self.assertEqual(data["title"], "Updated Title")
        self.assertEqual(data["status"], "DOING")

    def test_patch_task_both_title_and_status(self):
        """PATCH /api/tasks/<id> updates both title and status simultaneously."""
        created = self.post("/api/tasks", {"title": "Initial", "status": "TODO"}).json()
        task_id = created["id"]

        res = self.patch(f"/api/tasks/{task_id}", {"title": "Modified Title", "status": "DONE"})
        self.assertEqual(res.status, 200)
        data = res.json()
        self.assertEqual(data["title"], "Modified Title")
        self.assertEqual(data["status"], "DONE")

    def test_patch_task_not_found(self):
        """PATCH /api/tasks/<id> with non-existent ID returns 404 Not Found."""
        res = self.patch("/api/tasks/99999", {"status": "DOING"})
        self.assertEqual(res.status, 404)
        self.assertIn("error", res.json())

    def test_patch_task_validation_errors(self):
        """PATCH /api/tasks/<id> invalid payloads return 400 Bad Request."""
        created = self.post("/api/tasks", {"title": "Valid Task"}).json()
        task_id = created["id"]

        # Non-integer ID in URL
        res = self.patch("/api/tasks/abc", {"status": "DOING"})
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

        # Empty body with no fields
        res = self.patch(f"/api/tasks/{task_id}", {})
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

        # Malformed JSON
        res = self.patch(
            f"/api/tasks/{task_id}",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

        # Empty / whitespace-only title
        for invalid_title in ("", "   "):
            res = self.patch(f"/api/tasks/{task_id}", {"title": invalid_title})
            self.assertEqual(res.status, 400)
            self.assertIn("error", res.json())

        # Invalid status value
        res = self.patch(f"/api/tasks/{task_id}", {"status": "INVALID"})
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

    # -------------------------------------------------------------------------
    # 6. Delete Task (DELETE /api/tasks/<id>) Tests
    # -------------------------------------------------------------------------

    def test_delete_task_success(self):
        """DELETE /api/tasks/<id> removes the task and returns {'status': 'deleted', 'id': <id>}."""
        created = self.post("/api/tasks", {"title": "Task To Delete"}).json()
        task_id = created["id"]

        res = self.delete(f"/api/tasks/{task_id}")
        self.assertEqual(res.status, 200)
        self.assertEqual(res.json(), {"status": "deleted", "id": task_id})

        # Ensure task is no longer returned in GET /api/tasks
        tasks = self.get("/api/tasks").json()
        self.assertEqual(len(tasks), 0)

        # Subsequent GET/PATCH/DELETE on deleted ID must return 404
        self.assertEqual(self.delete(f"/api/tasks/{task_id}").status, 404)
        self.assertEqual(self.patch(f"/api/tasks/{task_id}", {"status": "DONE"}).status, 404)

    def test_delete_task_not_found(self):
        """DELETE /api/tasks/<id> on non-existent task returns 404 Not Found."""
        res = self.delete("/api/tasks/99999")
        self.assertEqual(res.status, 404)
        self.assertIn("error", res.json())

    def test_delete_task_invalid_id(self):
        """DELETE /api/tasks/<id> with non-integer ID returns 400 Bad Request."""
        res = self.delete("/api/tasks/invalid-id")
        self.assertEqual(res.status, 400)
        self.assertIn("error", res.json())

    # -------------------------------------------------------------------------
    # 7. Static File Serving Tests
    # -------------------------------------------------------------------------

    def test_static_file_root_serves_html(self):
        """GET / must serve index.html with Content-Type text/html."""
        res = self.get("/")
        self.assertEqual(res.status, 200)
        self.assertIn("text/html", res.headers.get("Content-Type", "").lower())
        self.assertGreater(len(res.body_bytes), 0)

    def test_static_file_index_html_serves_html(self):
        """GET /index.html must serve index.html with Content-Type text/html."""
        res = self.get("/index.html")
        self.assertEqual(res.status, 200)
        self.assertIn("text/html", res.headers.get("Content-Type", "").lower())
        self.assertGreater(len(res.body_bytes), 0)

    def test_static_file_style_css_serves_css(self):
        """GET /style.css must serve style.css with Content-Type text/css."""
        res = self.get("/style.css")
        self.assertEqual(res.status, 200)
        self.assertIn("text/css", res.headers.get("Content-Type", "").lower())
        self.assertGreater(len(res.body_bytes), 0)

    def test_static_file_app_js_serves_javascript(self):
        """GET /app.js must serve app.js with Content-Type application/javascript or text/javascript."""
        res = self.get("/app.js")
        self.assertEqual(res.status, 200)
        ct = res.headers.get("Content-Type", "").lower()
        self.assertTrue("javascript" in ct, f"Expected javascript Content-Type, got: {ct}")
        self.assertGreater(len(res.body_bytes), 0)

    def test_static_file_not_found(self):
        """GET /nonexistent.txt must return 404 Not Found."""
        res = self.get("/nonexistent_static_asset_test_123.txt")
        self.assertEqual(res.status, 404)

    def test_static_file_directory_traversal_rejected(self):
        """Directory traversal attempts (../ or ..%2F) must be rejected with 403 or 404."""
        for attack_path in ("/../app/server.py", "/..%2Fapp%2Fserver.py", "/web/../../etc/passwd"):
            res = self.get(attack_path)
            self.assertIn(
                res.status,
                (403, 404),
                f"Expected 403 or 404 for traversal path={attack_path}, got {res.status}",
            )

    # -------------------------------------------------------------------------
    # 8. Single Task Retrieval (GET /api/tasks/<id>) & Route Edge Cases
    # -------------------------------------------------------------------------

    def test_get_single_task_success(self):
        """GET /api/tasks/<id> retrieves an existing task by ID."""
        created = self.post("/api/tasks", {"title": "Single Task", "status": "DOING"}).json()
        task_id = created["id"]

        res = self.get(f"/api/tasks/{task_id}")
        self.assertEqual(res.status, 200)
        data = res.json()
        self.assertEqual(data["id"], task_id)
        self.assertEqual(data["title"], "Single Task")
        self.assertEqual(data["status"], "DOING")

    def test_get_single_task_not_found(self):
        """GET /api/tasks/<id> with non-existent ID returns 404 Not Found."""
        res = self.get("/api/tasks/99999")
        self.assertEqual(res.status, 404)
        self.assertIn("error", res.json())

    def test_get_single_task_invalid_id(self):
        """GET /api/tasks/<id> with non-integer or non-positive ID returns 400 Bad Request."""
        for invalid_path in ("/api/tasks/abc", "/api/tasks/-1", "/api/tasks/0"):
            res = self.get(invalid_path)
            self.assertEqual(res.status, 400, f"Expected 400 for path={invalid_path}")
            self.assertIn("error", res.json())

    def test_unknown_api_endpoints_return_404_json(self):
        """Unknown /api endpoints must return 404 with JSON error payload."""
        for unknown_path in ("/api", "/api/", "/api/unknown", "/api/v1/tasks"):
            res = self.get(unknown_path)
            self.assertEqual(res.status, 404, f"Expected 404 for path={unknown_path}")
            self.assertIn("application/json", res.headers.get("Content-Type", ""))
            self.assertIn("error", res.json())

    def test_cors_options_preflight(self):
        """OPTIONS request returns 204 No Content with CORS allow headers."""
        res = self.options("/api/tasks")
        self.assertEqual(res.status, 204)
        self.assertEqual(res.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("GET", res.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("POST", res.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("PATCH", res.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("DELETE", res.headers.get("Access-Control-Allow-Methods", ""))


if __name__ == "__main__":
    unittest.main()
