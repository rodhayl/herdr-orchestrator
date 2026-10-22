#!/usr/bin/env python3
"""
scripts/smoke_test.py
Standalone 12-step deterministic smoke verification script for MiniBoard.
Executes an end-to-end verification scenario against an ephemeral server instance,
outputs clear progress logs for each step, and exits with code 0 on total success
or non-zero on any failure.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
from typing import Any, Optional, Tuple

# Ensure repository root is on sys.path for direct imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.server import create_server


def make_request(
    base_url: str,
    method: str,
    path: str,
    payload: Optional[dict] = None,
) -> Tuple[int, Any, dict]:
    """Sends an HTTP request and returns (status_code, parsed_body_or_string, headers)."""
    url = f"{base_url}{path}"
    headers = {}
    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            status = resp.status
            body = resp.read()
            resp_headers = dict(resp.headers)
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:
                parsed = body.decode("utf-8", errors="replace")
            return status, parsed, resp_headers
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read()
        resp_headers = dict(e.headers)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = body.decode("utf-8", errors="replace")
        return status, parsed, resp_headers


def run_smoke_test() -> int:
    """Executes the 12-step deterministic smoke test suite."""
    print("=" * 70)
    print("MiniBoard End-to-End Smoke Test: Starting 12-Step Verification")
    print("=" * 70)

    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "smoke_test.db")
    server = None
    thread = None

    try:
        # ---------------------------------------------------------------------
        # Step 1 - Server Bootstrap
        # ---------------------------------------------------------------------
        print("[Step 1/12] Server Bootstrap: Starting server on 127.0.0.1:0 with isolated DB...")
        server, thread = create_server(host="127.0.0.1", port=0, db_path=db_path)
        port = server.server_port
        assert port > 0, f"Expected positive ephemeral port, got {port}"
        base_url = f"http://127.0.0.1:{port}"
        print(f"  -> Bound to ephemeral port {port}. Base URL: {base_url}")
        print("  -> Step 1 PASS")

        # ---------------------------------------------------------------------
        # Step 2 - Health Check
        # ---------------------------------------------------------------------
        print("[Step 2/12] Health Check: GET /health...")
        status, body, headers = make_request(base_url, "GET", "/health")
        assert status == 200, f"Expected HTTP 200, got {status}: {body}"
        assert isinstance(body, dict), f"Expected JSON dict, got {type(body)}"
        assert body.get("status") == "ok", f"Expected {{'status': 'ok'}}, got {body}"
        print(f"  -> Response: {body}")
        print("  -> Step 2 PASS")

        # ---------------------------------------------------------------------
        # Step 3 - Initial Empty State
        # ---------------------------------------------------------------------
        print("[Step 3/12] Initial Empty State: GET /api/tasks...")
        status, body, _ = make_request(base_url, "GET", "/api/tasks")
        assert status == 200, f"Expected HTTP 200, got {status}: {body}"
        assert isinstance(body, list), f"Expected JSON list, got {type(body)}"
        assert len(body) == 0, f"Expected empty list [], got {body}"
        print("  -> Verified initial empty task list []")
        print("  -> Step 3 PASS")

        # ---------------------------------------------------------------------
        # Step 4 - Create Task (Valid)
        # ---------------------------------------------------------------------
        print("[Step 4/12] Create Task (Valid): POST /api/tasks (title='Smoke Task 1', status='TODO')...")
        payload = {"title": "Smoke Task 1", "status": "TODO"}
        status, body, _ = make_request(base_url, "POST", "/api/tasks", payload)
        assert status == 201, f"Expected HTTP 201, got {status}: {body}"
        assert isinstance(body, dict), f"Expected JSON dict, got {type(body)}"
        task_id = body.get("id")
        assert isinstance(task_id, int) and task_id > 0, f"Expected positive integer id, got {task_id}"
        assert body.get("title") == "Smoke Task 1", f"Expected title 'Smoke Task 1', got {body.get('title')}"
        assert body.get("status") == "TODO", f"Expected status 'TODO', got {body.get('status')}"
        assert body.get("created_at"), f"Expected non-empty created_at timestamp"
        assert body.get("updated_at"), f"Expected non-empty updated_at timestamp"
        print(f"  -> Created task id={task_id}, title='{body.get('title')}', status='{body.get('status')}'")
        print("  -> Step 4 PASS")

        # ---------------------------------------------------------------------
        # Step 5 - Create Task Validation Error
        # ---------------------------------------------------------------------
        print("[Step 5/12] Create Task Validation Error: POST /api/tasks with empty title...")
        invalid_payload = {"title": ""}
        status, body, _ = make_request(base_url, "POST", "/api/tasks", invalid_payload)
        assert status == 400, f"Expected HTTP 400, got {status}: {body}"
        assert isinstance(body, dict) and "error" in body, f"Expected JSON error response, got {body}"
        print(f"  -> Correctly rejected with HTTP 400: {body}")
        print("  -> Step 5 PASS")

        # ---------------------------------------------------------------------
        # Step 6 - Verify Task Listing
        # ---------------------------------------------------------------------
        print("[Step 6/12] Verify Task Listing: GET /api/tasks...")
        status, body, _ = make_request(base_url, "GET", "/api/tasks")
        assert status == 200, f"Expected HTTP 200, got {status}: {body}"
        assert isinstance(body, list) and len(body) == 1, f"Expected exactly 1 task, got {body}"
        listed_task = body[0]
        assert listed_task["id"] == task_id, f"Expected id {task_id}, got {listed_task['id']}"
        assert listed_task["title"] == "Smoke Task 1", f"Expected title 'Smoke Task 1', got {listed_task['title']}"
        assert listed_task["status"] == "TODO", f"Expected status 'TODO', got {listed_task['status']}"
        print(f"  -> Verified task listing contains exactly Task 1 (id={task_id})")
        print("  -> Step 6 PASS")

        # ---------------------------------------------------------------------
        # Step 7 - Update Status
        # ---------------------------------------------------------------------
        print(f"[Step 7/12] Update Status: PATCH /api/tasks/{task_id} (status='DOING')...")
        status, body, _ = make_request(base_url, "PATCH", f"/api/tasks/{task_id}", {"status": "DOING"})
        assert status == 200, f"Expected HTTP 200, got {status}: {body}"
        assert body.get("id") == task_id, f"Expected id {task_id}, got {body.get('id')}"
        assert body.get("status") == "DOING", f"Expected status 'DOING', got {body.get('status')}"
        assert body.get("title") == "Smoke Task 1", f"Expected title unchanged, got {body.get('title')}"
        print(f"  -> Task id={task_id} updated: status='{body.get('status')}'")
        print("  -> Step 7 PASS")

        # ---------------------------------------------------------------------
        # Step 8 - Update Title
        # ---------------------------------------------------------------------
        print(f"[Step 8/12] Update Title: PATCH /api/tasks/{task_id} (title='Smoke Task 1 Updated')...")
        status, body, _ = make_request(
            base_url, "PATCH", f"/api/tasks/{task_id}", {"title": "Smoke Task 1 Updated"}
        )
        assert status == 200, f"Expected HTTP 200, got {status}: {body}"
        assert body.get("id") == task_id, f"Expected id {task_id}, got {body.get('id')}"
        assert body.get("title") == "Smoke Task 1 Updated", f"Expected updated title, got {body.get('title')}"
        assert body.get("status") == "DOING", f"Expected status 'DOING' preserved, got {body.get('status')}"
        print(f"  -> Task id={task_id} updated: title='{body.get('title')}'")
        print("  -> Step 8 PASS")

        # ---------------------------------------------------------------------
        # Step 9 - Update Non-Existent Task
        # ---------------------------------------------------------------------
        print("[Step 9/12] Update Non-Existent Task: PATCH /api/tasks/99999 (status='DONE')...")
        status, body, _ = make_request(base_url, "PATCH", "/api/tasks/99999", {"status": "DONE"})
        assert status == 404, f"Expected HTTP 404, got {status}: {body}"
        assert isinstance(body, dict) and "error" in body, f"Expected JSON error response, got {body}"
        print(f"  -> Correctly rejected with HTTP 404: {body}")
        print("  -> Step 9 PASS")

        # ---------------------------------------------------------------------
        # Step 10 - Delete Task
        # ---------------------------------------------------------------------
        print(f"[Step 10/12] Delete Task: DELETE /api/tasks/{task_id}...")
        status, body, _ = make_request(base_url, "DELETE", f"/api/tasks/{task_id}")
        assert status == 200, f"Expected HTTP 200, got {status}: {body}"
        assert body.get("status") == "deleted", f"Expected status 'deleted', got {body.get('status')}"
        assert body.get("id") == task_id, f"Expected id {task_id}, got {body.get('id')}"
        print(f"  -> Deleted task id={task_id}: {body}")
        print("  -> Step 10 PASS")

        # ---------------------------------------------------------------------
        # Step 11 - Delete Non-Existent Task
        # ---------------------------------------------------------------------
        print("[Step 11/12] Delete Non-Existent Task: DELETE /api/tasks/99999...")
        status, body, _ = make_request(base_url, "DELETE", "/api/tasks/99999")
        assert status == 404, f"Expected HTTP 404, got {status}: {body}"
        assert isinstance(body, dict) and "error" in body, f"Expected JSON error response, got {body}"
        print(f"  -> Correctly rejected with HTTP 404: {body}")
        print("  -> Step 11 PASS")

        # ---------------------------------------------------------------------
        # Step 12 - Verify Static Asset Delivery
        # ---------------------------------------------------------------------
        print("[Step 12/12] Verify Static Asset Delivery: GET /, /style.css, /app.js...")
        static_assets = [
            ("/", "text/html"),
            ("/style.css", "text/css"),
            ("/app.js", "javascript"),
        ]
        for asset_path, expected_mime in static_assets:
            req = urllib.request.Request(f"{base_url}{asset_path}")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                assert resp.status == 200, f"Expected HTTP 200 for {asset_path}, got {resp.status}"
                content = resp.read()
                assert len(content) > 0, f"Expected non-empty response for {asset_path}"
                content_type = resp.headers.get("Content-Type", "").lower()
                assert (
                    expected_mime in content_type
                ), f"Expected MIME containing '{expected_mime}' for {asset_path}, got '{content_type}'"
                print(f"  -> Asset {asset_path}: 200 OK (Content-Type: {content_type}, size: {len(content)} bytes)")
        print("  -> Step 12 PASS")

        print("=" * 70)
        print("SUCCESS: All 12 smoke test steps completed successfully!")
        print("=" * 70)
        return 0

    except Exception as exc:
        print(f"\n[FAILURE] Smoke test failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    finally:
        # Cleanup: shut down server and remove temporary files
        print("[Cleanup] Cleaning up resources...")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as e:
                print(f"  -> Warning during server shutdown: {e}", file=sys.stderr)
        if thread is not None:
            try:
                thread.join(timeout=5.0)
            except Exception as e:
                print(f"  -> Warning joining server thread: {e}", file=sys.stderr)
        try:
            temp_dir.cleanup()
        except Exception as e:
            print(f"  -> Warning cleaning temp directory: {e}", file=sys.stderr)
        print("  -> Cleanup complete.")


if __name__ == "__main__":
    sys.exit(run_smoke_test())
