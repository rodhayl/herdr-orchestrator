#!/usr/bin/env python3
"""
MiniLinks Standalone 12-Step Smoke Test Script.

Executes an end-to-end verification scenario against an ephemeral server instance,
printing deterministic progress logs for each step and exiting with code 0 on success.
"""

import json
import os
import shutil
import sys
import tempfile
import time
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
        print(f"FATAL: Could not import create_server. sys.path={sys.path}", file=sys.stderr)
        raise _err


def http_request(base_url: str, method: str, path: str, data=None):
    """
    Sends an HTTP request using urllib and returns (status, headers, json_body, raw_body).
    Handles HTTPError gracefully to inspect 4xx/5xx responses.
    """
    url = f"{base_url}{path}"
    headers = {}
    body = None

    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read()
            json_data = None
            if resp_body:
                try:
                    json_data = json.loads(resp_body.decode("utf-8"))
                except Exception:
                    pass
            return resp.status, resp.headers, json_data, resp_body
    except urllib.error.HTTPError as err:
        err_body = err.read()
        json_data = None
        if err_body:
            try:
                json_data = json.loads(err_body.decode("utf-8"))
            except Exception:
                pass
        return err.code, err.headers, json_data, err_body


def main() -> int:
    """Runs the 12 deterministic smoke test steps."""
    server = None
    temp_dir = None

    print("==================================================")
    print("Starting MiniLinks 12-Step Standalone Smoke Test")
    print("==================================================")

    try:
        # Step 1 - Server Bootstrap
        temp_dir = tempfile.mkdtemp(prefix="minilinks_smoke_")
        db_path = os.path.join(temp_dir, "smoke.db")
        server = create_server(host="127.0.0.1", port=0, db_path=db_path)
        port = getattr(server, "server_port", None) or server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        print(f"[Step 1/12] Server Bootstrap: Bound to ephemeral port {port}, DB at {db_path}")

        # Step 2 - Health Check
        status, _, data, _ = http_request(base_url, "GET", "/health")
        assert status == 200, f"Step 2 failed: expected HTTP 200, got {status}"
        assert isinstance(data, dict) and data.get("status") == "ok", (
            f"Step 2 failed: expected {{'status': 'ok'}}, got {data}"
        )
        print("[Step 2/12] Health Check: GET /health returned 200 OK and {'status': 'ok'}")

        # Step 3 - Initial Empty State
        status, _, data, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status == 200, f"Step 3 failed: expected HTTP 200, got {status}"
        assert isinstance(data, list) and len(data) == 0, (
            f"Step 3 failed: expected empty list [], got {data}"
        )
        print("[Step 3/12] Initial Empty State: GET /api/bookmarks returned 200 OK with empty list []")

        # Step 4 - Create Bookmark (Valid)
        payload = {
            "title": "Python Docs",
            "url": "https://docs.python.org",
            "notes": "Official Docs",
        }
        status, _, data, _ = http_request(base_url, "POST", "/api/bookmarks", data=payload)
        assert status == 201, f"Step 4 failed: expected HTTP 201, got {status}"
        assert isinstance(data, dict), f"Step 4 failed: expected JSON dict, got {type(data)}"
        created_id = data.get("id")
        assert isinstance(created_id, int) and created_id > 0, (
            f"Step 4 failed: invalid bookmark id: {created_id}"
        )
        assert data.get("title") == "Python Docs", f"Step 4 failed: title mismatch: {data.get('title')}"
        assert data.get("url") == "https://docs.python.org", f"Step 4 failed: url mismatch: {data.get('url')}"
        assert data.get("notes") == "Official Docs", f"Step 4 failed: notes mismatch: {data.get('notes')}"
        assert bool(data.get("created_at")), "Step 4 failed: missing created_at"
        assert bool(data.get("updated_at")), "Step 4 failed: missing updated_at"
        print(f"[Step 4/12] Create Bookmark (Valid): POST /api/bookmarks returned 201 Created (ID: {created_id})")

        # Step 5 - Create Bookmark Validation Error
        status, _, data, _ = http_request(base_url, "POST", "/api/bookmarks", data={"title": ""})
        assert status == 400, f"Step 5 failed: expected HTTP 400 for empty title, got {status}"
        print("[Step 5/12] Create Bookmark Validation Error: POST /api/bookmarks with invalid payload returned 400 Bad Request")

        # Step 6 - Verify Bookmark Listing
        status, _, data, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status == 200, f"Step 6 failed: expected HTTP 200, got {status}"
        assert isinstance(data, list) and len(data) == 1, (
            f"Step 6 failed: expected exactly 1 bookmark in list, got {len(data) if isinstance(data, list) else data}"
        )
        bm = data[0]
        assert bm.get("id") == created_id, f"Step 6 failed: bookmark ID mismatch: {bm.get('id')}"
        assert bm.get("title") == "Python Docs", f"Step 6 failed: title mismatch: {bm.get('title')}"
        assert bm.get("url") == "https://docs.python.org", f"Step 6 failed: url mismatch: {bm.get('url')}"
        assert bm.get("notes") == "Official Docs", f"Step 6 failed: notes mismatch: {bm.get('notes')}"
        print("[Step 6/12] Verify Bookmark Listing: GET /api/bookmarks returned 200 OK with 1 matching bookmark")

        # Step 7 - Search Filtering
        status, _, data_match, _ = http_request(base_url, "GET", "/api/bookmarks?q=Python")
        assert status == 200, f"Step 7 failed: expected HTTP 200 for search, got {status}"
        assert isinstance(data_match, list) and len(data_match) == 1, (
            f"Step 7 failed: expected 1 match for 'Python', got {len(data_match) if isinstance(data_match, list) else data_match}"
        )
        assert data_match[0]["id"] == created_id

        status, _, data_nomatch, _ = http_request(base_url, "GET", "/api/bookmarks?q=NonExistentTerm")
        assert status == 200, f"Step 7 failed: expected HTTP 200 for non-matching search, got {status}"
        assert isinstance(data_nomatch, list) and len(data_nomatch) == 0, (
            f"Step 7 failed: expected 0 matches for 'NonExistentTerm', got {len(data_nomatch) if isinstance(data_nomatch, list) else data_nomatch}"
        )
        print("[Step 7/12] Search Filtering: GET /api/bookmarks?q=Python returned 1 match; q=NonExistentTerm returned 0")

        # Step 8 - Update Bookmark
        time.sleep(0.05)
        status, _, data, _ = http_request(
            base_url,
            "PATCH",
            f"/api/bookmarks/{created_id}",
            data={"notes": "Updated Documentation Notes"},
        )
        assert status == 200, f"Step 8 failed: expected HTTP 200, got {status}"
        assert data.get("notes") == "Updated Documentation Notes", (
            f"Step 8 failed: notes mismatch after update: {data.get('notes')}"
        )
        assert bool(data.get("updated_at")), "Step 8 failed: missing updated_at after patch"
        print(f"[Step 8/12] Update Bookmark: PATCH /api/bookmarks/{created_id} returned 200 OK, notes updated")

        # Step 9 - Update Non-Existent Bookmark
        status, _, data, _ = http_request(
            base_url,
            "PATCH",
            "/api/bookmarks/99999",
            data={"notes": "Ghost"},
        )
        assert status == 404, f"Step 9 failed: expected HTTP 404 for non-existent bookmark, got {status}"
        print("[Step 9/12] Update Non-Existent Bookmark: PATCH /api/bookmarks/99999 returned 404 Not Found")

        # Step 10 - Delete Bookmark
        status, _, data, _ = http_request(base_url, "DELETE", f"/api/bookmarks/{created_id}")
        assert status == 200, f"Step 10 failed: expected HTTP 200, got {status}"
        assert isinstance(data, dict), f"Step 10 failed: expected dict, got {type(data)}"
        assert data.get("status") == "deleted", f"Step 10 failed: expected status 'deleted', got {data.get('status')}"
        assert data.get("id") == created_id, f"Step 10 failed: expected id {created_id}, got {data.get('id')}"
        print(f"[Step 10/12] Delete Bookmark: DELETE /api/bookmarks/{created_id} returned 200 OK (status: deleted)")

        # Step 11 - Delete Non-Existent Bookmark
        status, _, data, _ = http_request(base_url, "DELETE", "/api/bookmarks/99999")
        assert status == 404, f"Step 11 failed: expected HTTP 404 for non-existent delete, got {status}"
        print("[Step 11/12] Delete Non-Existent Bookmark: DELETE /api/bookmarks/99999 returned 404 Not Found")

        # Step 12 - Verify Static Asset Delivery
        static_endpoints = ["/", "/style.css", "/app.js"]
        for path in static_endpoints:
            status, _, _, body = http_request(base_url, "GET", path)
            assert status == 200, f"Step 12 failed: expected HTTP 200 for {path}, got {status}"
            assert len(body) > 0, f"Step 12 failed: expected non-empty content for {path}, got 0 bytes"
        print("[Step 12/12] Verify Static Asset Delivery: GET /, /style.css, and /app.js returned 200 OK with non-empty content")

        print("==================================================")
        print("ALL 12 SMOKE TEST STEPS COMPLETED SUCCESSFULLY!")
        print("==================================================")
        return 0

    except AssertionError as assert_err:
        print(f"\n[FAILURE] Assertion failed: {assert_err}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\n[FAILURE] Unexpected error occurred: {exc}", file=sys.stderr)
        return 1
    finally:
        # Cleanup
        print("[Cleanup] Cleaning up background server and temporary resources...")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as e:
                print(f"[Cleanup] Error shutting down server: {e}", file=sys.stderr)
        if temp_dir is not None and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                print(f"[Cleanup] Error removing temporary dir: {e}", file=sys.stderr)
        print("[Cleanup] Done.")


if __name__ == "__main__":
    sys.exit(main())
