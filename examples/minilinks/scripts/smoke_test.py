#!/usr/bin/env python3
"""
Standalone 12-Step Deterministic Smoke Test for MiniLinks.

Executes an end-to-end verification scenario against an ephemeral server instance:
  Step 1  - Server Bootstrap
  Step 2  - Health Check
  Step 3  - Initial Empty State
  Step 4  - Create Bookmark (Valid)
  Step 5  - Create Bookmark Validation Error
  Step 6  - Verify Bookmark Listing
  Step 7  - Search Filtering
  Step 8  - Update Bookmark
  Step 9  - Update Non-Existent Bookmark
  Step 10 - Delete Bookmark
  Step 11 - Delete Non-Existent Bookmark
  Step 12 - Verify Static Asset Delivery

Exits with status code 0 on total success, or non-zero on any failure.
"""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

# Ensure examples/minilinks and project root are in sys.path so 'app' can be imported
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
    from app.server import MiniLinksServer, create_server
except (ImportError, AttributeError):
    from examples.minilinks.app.server import MiniLinksServer, create_server


def http_request(
    base_url: str,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any, bytes]:
    """
    Sends an HTTP request using urllib with Connection: close.
    Returns (status_code, parsed_json_or_none, raw_body_bytes).
    """
    url = f"{base_url}{path}"
    headers = {"Connection": "close"}
    data_bytes: Optional[bytes] = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read()

    parsed_json = None
    if body:
        try:
            parsed_json = json.loads(body.decode("utf-8"))
        except Exception:
            parsed_json = None

    return status, parsed_json, body


def run_smoke_test() -> None:
    """Executes the 12 deterministic smoke test steps."""
    print("=" * 70)
    print("MiniLinks 12-Step Smoke Test Verification Suite")
    print("=" * 70)

    temp_dir = tempfile.TemporaryDirectory()
    server: Optional[MiniLinksServer] = None

    try:
        # Step 1: Server Bootstrap
        print("[Step 1/12] Server Bootstrap: starting server on ephemeral port...")
        temp_db = os.path.join(temp_dir.name, "smoke_test.db")
        server = create_server(host="127.0.0.1", port=0, db_path=temp_db)
        bound_port = server.server_port
        assert bound_port > 0, f"Expected positive port number, got {bound_port}"
        assert any(t.is_alive() and t.daemon for t in threading.enumerate()), (
            "Expected daemon server thread"
        )
        base_url = f"http://127.0.0.1:{bound_port}"
        print(f"  --> PASS: Server listening at {base_url} (db: {temp_db})")

        # Step 2: Health Check
        print("[Step 2/12] Health Check: GET /health...")
        status, payload, _ = http_request(base_url, "GET", "/health")
        assert status == 200, f"Expected HTTP 200, got {status} ({payload})"
        assert payload == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {payload}"
        print(f"  --> PASS: Health check returned HTTP 200: {payload}")

        # Step 3: Initial Empty State
        print("[Step 3/12] Initial Empty State: GET /api/bookmarks...")
        status, payload, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status == 200, f"Expected HTTP 200, got {status} ({payload})"
        assert isinstance(payload, list) and len(payload) == 0, (
            f"Expected empty list [], got {payload}"
        )
        print("  --> PASS: Initial bookmarks list is empty []")

        # Step 4: Create Bookmark (Valid)
        print("[Step 4/12] Create Bookmark (Valid): POST /api/bookmarks...")
        create_payload = {
            "title": "Python Docs",
            "url": "https://docs.python.org",
            "notes": "Official Docs",
        }
        status, payload, _ = http_request(
            base_url, "POST", "/api/bookmarks", payload=create_payload
        )
        assert status == 201, f"Expected HTTP 201, got {status} ({payload})"
        assert isinstance(payload, dict), f"Expected dict response, got {type(payload)}"
        bm_id = payload.get("id")
        assert isinstance(bm_id, int) and bm_id > 0, (
            f"Expected positive integer 'id', got {bm_id}"
        )
        assert payload.get("title") == "Python Docs", f"Unexpected title: {payload.get('title')}"
        assert payload.get("url") == "https://docs.python.org", (
            f"Unexpected url: {payload.get('url')}"
        )
        assert payload.get("notes") == "Official Docs", (
            f"Unexpected notes: {payload.get('notes')}"
        )
        created_at = payload.get("created_at")
        updated_at = payload.get("updated_at")
        assert created_at and isinstance(created_at, str), f"Missing created_at: {created_at}"
        assert updated_at and isinstance(updated_at, str), f"Missing updated_at: {updated_at}"

        # Verify sqlite3 persistence directly
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, url FROM bookmarks WHERE id = ?", (bm_id,))
            row = cursor.fetchone()
            assert row is not None, f"Bookmark {bm_id} not found in sqlite3 database"
            assert row[1] == "Python Docs"
        finally:
            conn.close()

        print(f"  --> PASS: Created bookmark with ID {bm_id} at {created_at}")

        # Step 5: Create Bookmark Validation Error
        print("[Step 5/12] Create Bookmark Validation Error: POST /api/bookmarks with invalid payload...")
        status, payload, _ = http_request(
            base_url, "POST", "/api/bookmarks", payload={"title": ""}
        )
        assert status == 400, f"Expected HTTP 400, got {status} ({payload})"
        assert isinstance(payload, dict) and "error" in payload, (
            f"Expected error payload, got {payload}"
        )
        print(f"  --> PASS: Rejected invalid creation payload with HTTP 400: {payload.get('error')}")

        # Step 6: Verify Bookmark Listing
        print("[Step 6/12] Verify Bookmark Listing: GET /api/bookmarks...")
        status, payload, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status == 200, f"Expected HTTP 200, got {status} ({payload})"
        assert isinstance(payload, list) and len(payload) == 1, (
            f"Expected list with 1 item, got {len(payload)}"
        )
        item = payload[0]
        assert item.get("id") == bm_id, f"Expected id {bm_id}, got {item.get('id')}"
        assert item.get("title") == "Python Docs", f"Unexpected title: {item.get('title')}"
        assert item.get("url") == "https://docs.python.org", f"Unexpected url: {item.get('url')}"
        assert item.get("notes") == "Official Docs", f"Unexpected notes: {item.get('notes')}"
        print(f"  --> PASS: Listing returned exactly 1 bookmark matching ID {bm_id}")

        # Step 7: Search Filtering
        print("[Step 7/12] Search Filtering: GET /api/bookmarks?q=Python and ?q=NonExistentTerm...")
        status, payload, _ = http_request(base_url, "GET", "/api/bookmarks?q=Python")
        assert status == 200, f"Expected HTTP 200, got {status}"
        assert isinstance(payload, list) and len(payload) == 1, (
            f"Expected 1 matching result for 'Python', got {len(payload)}"
        )
        assert payload[0].get("id") == bm_id

        status, payload_empty, _ = http_request(
            base_url, "GET", "/api/bookmarks?q=NonExistentTerm"
        )
        assert status == 200, f"Expected HTTP 200, got {status}"
        assert isinstance(payload_empty, list) and len(payload_empty) == 0, (
            f"Expected 0 results for non-matching term, got {len(payload_empty)}"
        )
        print("  --> PASS: Search correctly filtered matching and non-matching queries")

        # Step 8: Update Bookmark
        print("[Step 8/12] Update Bookmark: PATCH /api/bookmarks/<id>...")
        # Brief pause to ensure updated_at timestamp increments past current second
        time.sleep(1.05)
        patch_payload = {"notes": "Updated Documentation Notes"}
        status, payload, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload=patch_payload
        )
        assert status == 200, f"Expected HTTP 200, got {status} ({payload})"
        assert isinstance(payload, dict), f"Expected dict response, got {type(payload)}"
        assert payload.get("notes") == "Updated Documentation Notes", (
            f"Expected updated notes, got {payload.get('notes')}"
        )
        new_updated_at = payload.get("updated_at")
        assert new_updated_at and new_updated_at != updated_at, (
            f"Expected refreshed updated_at ({new_updated_at} != {updated_at})"
        )
        print(f"  --> PASS: Updated bookmark notes; updated_at refreshed to {new_updated_at}")

        # Step 9: Update Non-Existent Bookmark
        print("[Step 9/12] Update Non-Existent Bookmark: PATCH /api/bookmarks/99999...")
        status, payload, _ = http_request(
            base_url, "PATCH", "/api/bookmarks/99999", payload={"notes": "Ghost"}
        )
        assert status == 404, f"Expected HTTP 404, got {status} ({payload})"
        assert isinstance(payload, dict) and "error" in payload, (
            f"Expected error field in 404 response, got {payload}"
        )
        print(f"  --> PASS: Non-existent PATCH returned HTTP 404: {payload.get('error')}")

        # Step 10: Delete Bookmark
        print(f"[Step 10/12] Delete Bookmark: DELETE /api/bookmarks/{bm_id}...")
        status, payload, _ = http_request(
            base_url, "DELETE", f"/api/bookmarks/{bm_id}"
        )
        assert status == 200, f"Expected HTTP 200, got {status} ({payload})"
        assert payload == {"status": "deleted", "id": bm_id}, (
            f"Expected {{'status': 'deleted', 'id': {bm_id}}}, got {payload}"
        )
        print(f"  --> PASS: Successfully deleted bookmark {bm_id}")

        # Step 11: Delete Non-Existent Bookmark
        print("[Step 11/12] Delete Non-Existent Bookmark: DELETE /api/bookmarks/99999...")
        status, payload, _ = http_request(base_url, "DELETE", "/api/bookmarks/99999")
        assert status == 404, f"Expected HTTP 404, got {status} ({payload})"
        assert isinstance(payload, dict) and "error" in payload, (
            f"Expected error field in 404 response, got {payload}"
        )
        print(f"  --> PASS: Non-existent DELETE returned HTTP 404: {payload.get('error')}")

        # Step 12: Verify Static Asset Delivery
        print("[Step 12/12] Verify Static Asset Delivery: GET /, /style.css, /app.js...")
        # Root index
        status_root, _, body_root = http_request(base_url, "GET", "/")
        assert status_root == 200, f"Expected HTTP 200 for /, got {status_root}"
        assert len(body_root) > 0, "Expected non-empty response body for /"
        assert b"MiniLinks" in body_root, "Expected 'MiniLinks' in root index response"

        # CSS stylesheet
        status_css, _, body_css = http_request(base_url, "GET", "/style.css")
        assert status_css == 200, f"Expected HTTP 200 for /style.css, got {status_css}"
        assert len(body_css) > 0, "Expected non-empty response body for /style.css"

        # JS client script
        status_js, _, body_js = http_request(base_url, "GET", "/app.js")
        assert status_js == 200, f"Expected HTTP 200 for /app.js, got {status_js}"
        assert len(body_js) > 0, "Expected non-empty response body for /app.js"
        print("  --> PASS: All static assets (/, /style.css, /app.js) served with HTTP 200")

        print("=" * 70)
        print("SUCCESS: All 12 deterministic smoke test steps passed!")
        print("=" * 70)

    finally:
        # Cleanup server and temporary database
        print("Cleaning up server and temporary test directory...")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as e:
                print(f"Warning during server shutdown: {e}")
        try:
            temp_dir.cleanup()
        except Exception as e:
            print(f"Warning during temp directory cleanup: {e}")
        print("Cleanup completed.")


def main() -> int:
    """Entry point for standalone execution."""
    try:
        run_smoke_test()
        return 0
    except AssertionError as e:
        print(f"\nASSERTION FAILED: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
