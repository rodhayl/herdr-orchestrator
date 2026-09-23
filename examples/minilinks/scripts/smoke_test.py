#!/usr/bin/env python3
"""
Standalone 12-Step Deterministic Smoke Test for MiniLinks.

Executes an end-to-end verification scenario against an ephemeral server instance:
  Step 1  - Server Bootstrap
  Step 2  - Health Check
  Step 3  - Initial Empty State
  Step 4  - Create Bookmark (Valid), Notes, Tags, and Archive Creation Semantics
  Step 5  - Create Bookmark Validation Errors (Title, URL, Notes, Tags, and Boolean Flags)
  Step 6  - Verify Bookmark Listing, Notes, Tags, and Archived Status
  Step 7  - Search & Tag Filtering across Title, URL, Notes, and Tags
  Step 8  - Update Bookmark, Notes, Favorite & Archive Toggling via PATCH
  Step 8b - Archive & Restore Semantics (POST /archive, /restore, ?archived= filtering)
  Step 9  - Update Non-Existent Bookmark
  Step 10 - Delete Bookmark
  Step 11 - Delete Non-Existent Bookmark
  Step 12 - Verify Static Asset Delivery (HTML, CSS, JS)

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
    from app import database
    from app.server import MiniLinksServer, create_server
    if not hasattr(database, "create_bookmark"):
        raise ImportError("Imported wrong database module")
except (ImportError, AttributeError):
    from examples.minilinks.app import database
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

        # Step 4: Create Bookmark (Valid), Notes, Tags, and Archive Creation Semantics
        print("[Step 4/12] Create Bookmark (Valid), Notes, Tags & Archive Semantics: POST /api/bookmarks...")
        create_payload = {
            "title": "Python Docs",
            "url": "https://docs.python.org",
            "notes": "Official Docs",
            "tags": ["docs", "python"],
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
        assert payload.get("tags") == ["docs", "python"], (
            f"Unexpected tags: {payload.get('tags')}"
        )
        assert payload.get("is_favorite") is False, (
            f"Expected is_favorite to default to False, got {payload.get('is_favorite')}"
        )
        assert isinstance(payload.get("is_favorite"), bool), (
            f"Expected is_favorite to be boolean, got {type(payload.get('is_favorite'))}"
        )
        assert payload.get("archived") is False, (
            f"Expected archived to default to False, got {payload.get('archived')}"
        )
        assert isinstance(payload.get("archived"), bool), (
            f"Expected archived to be boolean, got {type(payload.get('archived'))}"
        )
        created_at = payload.get("created_at")
        updated_at = payload.get("updated_at")
        assert created_at and isinstance(created_at, str), f"Missing created_at: {created_at}"
        assert updated_at and isinstance(updated_at, str), f"Missing updated_at: {updated_at}"

        # Verify sqlite3 persistence directly for notes, tags, favorite, and archived
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, url, notes, is_favorite, tags, archived FROM bookmarks WHERE id = ?",
                (bm_id,),
            )
            row = cursor.fetchone()
            assert row is not None, f"Bookmark {bm_id} not found in sqlite3 database"
            assert row[0] == bm_id, f"Expected id {bm_id}, got {row[0]}"
            assert row[1] == "Python Docs", f"Expected title 'Python Docs', got {row[1]}"
            assert row[2] == "https://docs.python.org", f"Expected url 'https://docs.python.org', got {row[2]}"
            assert row[3] == "Official Docs", f"Expected notes 'Official Docs' in sqlite3, got {row[3]}"
            assert row[4] == 0, f"Expected is_favorite=0 in sqlite3, got {row[4]}"
            assert json.loads(row[5]) == ["docs", "python"], f"Expected tags ['docs', 'python'] in sqlite3, got {row[5]}"
            assert row[6] == 0, f"Expected archived=0 in sqlite3, got {row[6]}"
        finally:
            conn.close()

        # Verify default empty notes string and empty tags list when omitted or explicitly null
        # 1. Omitted notes and tags default to "" and []
        status_omitted, payload_omitted, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Temp Omitted Notes", "url": "https://example.com/omitted"},
        )
        assert status_omitted == 201, f"Expected HTTP 201 for omitted notes, got {status_omitted}"
        assert payload_omitted.get("notes") == "", f"Expected empty string notes, got {payload_omitted.get('notes')}"
        assert payload_omitted.get("tags") == [], f"Expected empty list tags, got {payload_omitted.get('tags')}"
        assert payload_omitted.get("archived") is False, f"Expected archived False, got {payload_omitted.get('archived')}"
        temp_omitted_id = payload_omitted["id"]

        # 2. Null notes and null tags default to "" and []
        status_null, payload_null, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Temp Null Notes", "url": "https://example.com/null", "notes": None, "tags": None},
        )
        assert status_null == 201, f"Expected HTTP 201 for null notes, got {status_null}"
        assert payload_null.get("notes") == "", f"Expected empty string notes, got {payload_null.get('notes')}"
        assert payload_null.get("tags") == [], f"Expected empty list tags, got {payload_null.get('tags')}"
        assert payload_null.get("archived") is False
        temp_null_id = payload_null["id"]

        # 3. Explicit creation with archived: True
        status_arch_direct, payload_arch_direct, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Temp Archived Direct", "url": "https://example.com/archived-direct", "archived": True},
        )
        assert status_arch_direct == 201, f"Expected HTTP 201 for direct archived, got {status_arch_direct}"
        assert payload_arch_direct.get("archived") is True
        assert isinstance(payload_arch_direct.get("archived"), bool)
        temp_arch_id = payload_arch_direct["id"]

        # Clean up temporary test bookmarks so Step 6 has exactly 1 bookmark
        for temp_id in [temp_omitted_id, temp_null_id, temp_arch_id]:
            status_del, _, _ = http_request(base_url, "DELETE", f"/api/bookmarks/{temp_id}")
            assert status_del == 200, f"Failed to clean up temp bookmark {temp_id}"

        print(
            f"  --> PASS: Created bookmark with ID {bm_id} "
            f"(notes='Official Docs', tags=['docs', 'python'], is_favorite=False, archived=False) at {created_at}"
        )

        # Step 5: Create Bookmark Validation Errors
        print("[Step 5/12] Create Bookmark Validation Errors: testing empty title, non-string notes, invalid tags, and non-boolean flags...")
        # 1. Missing / empty title
        status, payload, _ = http_request(
            base_url, "POST", "/api/bookmarks", payload={"title": ""}
        )
        assert status == 400, f"Expected HTTP 400 for empty title, got {status} ({payload})"
        assert isinstance(payload, dict) and "error" in payload, (
            f"Expected error payload, got {payload}"
        )

        # 2. Non-string notes (numeric)
        status_num_notes, payload_num_notes, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "notes": 12345},
        )
        assert status_num_notes == 400, f"Expected HTTP 400 for non-string notes, got {status_num_notes}"
        assert payload_num_notes.get("error") == "Notes must be a string if provided"

        # 3. Non-string notes (list)
        status_list_notes, payload_list_notes, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "notes": ["invalid"]},
        )
        assert status_list_notes == 400, f"Expected HTTP 400 for list notes, got {status_list_notes}"
        assert payload_list_notes.get("error") == "Notes must be a string if provided"

        # 4. Non-boolean is_favorite
        status_invalid_fav, payload_invalid_fav, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "is_favorite": "true"},
        )
        assert status_invalid_fav == 400, f"Expected HTTP 400 for non-boolean is_favorite, got {status_invalid_fav}"
        assert payload_invalid_fav.get("error") == "is_favorite must be a boolean if provided"

        # 5. Non-boolean archived (string and integer)
        status_invalid_arch1, payload_invalid_arch1, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "archived": "true"},
        )
        assert status_invalid_arch1 == 400, f"Expected HTTP 400 for string archived, got {status_invalid_arch1}"
        assert payload_invalid_arch1.get("error") == "archived must be a boolean if provided"

        status_invalid_arch2, payload_invalid_arch2, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "archived": 1},
        )
        assert status_invalid_arch2 == 400, f"Expected HTTP 400 for integer archived, got {status_invalid_arch2}"
        assert payload_invalid_arch2.get("error") == "archived must be a boolean if provided"

        # 6. Invalid tags (not a list, or list containing non-string)
        status_bad_tags, payload_bad_tags, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "tags": "invalid_not_list"},
        )
        assert status_bad_tags == 400, f"Expected HTTP 400 for string tags, got {status_bad_tags}"

        status_bad_tags2, payload_bad_tags2, _ = http_request(
            base_url,
            "POST",
            "/api/bookmarks",
            payload={"title": "Valid Title", "url": "https://example.com", "tags": [123]},
        )
        assert status_bad_tags2 == 400, f"Expected HTTP 400 for non-string tag element, got {status_bad_tags2}"

        print("  --> PASS: Validation correctly rejected empty title, non-string notes, invalid tags, and non-boolean flags with HTTP 400")

        # Step 6: Verify Bookmark Listing & Notes
        print("[Step 6/12] Verify Bookmark Listing, Notes, Tags & Archived: GET /api/bookmarks...")
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
        assert item.get("tags") == ["docs", "python"], f"Unexpected tags: {item.get('tags')}"
        assert item.get("is_favorite") is False, (
            f"Expected is_favorite False, got {item.get('is_favorite')}"
        )
        assert item.get("archived") is False, (
            f"Expected archived False, got {item.get('archived')}"
        )
        assert isinstance(item.get("archived"), bool), (
            f"Expected archived to be boolean, got {type(item.get('archived'))}"
        )

        # Also verify GET /api/bookmarks/<id> returns complete object with notes, tags, and archived
        status_single, single_bm, _ = http_request(base_url, "GET", f"/api/bookmarks/{bm_id}")
        assert status_single == 200, f"Expected HTTP 200 for single retrieval, got {status_single}"
        assert single_bm.get("id") == bm_id
        assert single_bm.get("notes") == "Official Docs"
        assert single_bm.get("tags") == ["docs", "python"]
        assert single_bm.get("is_favorite") is False
        assert single_bm.get("archived") is False
        print(f"  --> PASS: Listing and single retrieval returned bookmark {bm_id} with notes='Official Docs', tags=['docs', 'python'], and archived=False")

        # Step 7: Search Filtering across Title, URL, and Notes
        print("[Step 7/12] Search & Tag Filtering: GET /api/bookmarks?q=..., GET /api/bookmarks?tag=..., and GET /api/tags...")
        # Search matching title
        status, payload_title, _ = http_request(base_url, "GET", "/api/bookmarks?q=Python")
        assert status == 200, f"Expected HTTP 200, got {status}"
        assert isinstance(payload_title, list) and len(payload_title) == 1, (
            f"Expected 1 matching result for 'Python', got {len(payload_title)}"
        )
        assert payload_title[0].get("id") == bm_id

        # Search matching notes substring ("Docs" matches notes "Official Docs")
        status_notes, payload_notes, _ = http_request(base_url, "GET", "/api/bookmarks?q=Docs")
        assert status_notes == 200, f"Expected HTTP 200, got {status_notes}"
        assert isinstance(payload_notes, list) and len(payload_notes) == 1, (
            f"Expected 1 matching result for 'Docs' (matching notes), got {len(payload_notes)}"
        )
        assert payload_notes[0].get("id") == bm_id
        assert payload_notes[0].get("notes") == "Official Docs"

        # Case-insensitive notes search ("official")
        status_case, payload_case, _ = http_request(base_url, "GET", "/api/bookmarks?q=official")
        assert status_case == 200, f"Expected HTTP 200, got {status_case}"
        assert isinstance(payload_case, list) and len(payload_case) == 1, (
            f"Expected 1 matching result for 'official' in notes, got {len(payload_case)}"
        )
        assert payload_case[0].get("id") == bm_id

        # Non-matching search query returns empty array
        status_empty, payload_empty, _ = http_request(
            base_url, "GET", "/api/bookmarks?q=NonExistentTerm"
        )
        assert status_empty == 200, f"Expected HTTP 200, got {status_empty}"
        assert isinstance(payload_empty, list) and len(payload_empty) == 0, (
            f"Expected 0 results for non-matching term, got {len(payload_empty)}"
        )

        # Tag filtering
        status_tag, payload_tag, _ = http_request(base_url, "GET", "/api/bookmarks?tag=python")
        assert status_tag == 200, f"Expected HTTP 200 for tag filter, got {status_tag}"
        assert isinstance(payload_tag, list) and len(payload_tag) == 1
        assert payload_tag[0].get("id") == bm_id

        # Tags listing endpoint
        status_tags, payload_tags, _ = http_request(base_url, "GET", "/api/tags")
        assert status_tags == 200, f"Expected HTTP 200 for /api/tags, got {status_tags}"
        assert payload_tags == {"tags": ["docs", "python"]}, f"Expected {{'tags': ['docs', 'python']}}, got {payload_tags}"

        # Non-matching tag filter
        status_notag, payload_notag, _ = http_request(base_url, "GET", "/api/bookmarks?tag=nonexistent")
        assert status_notag == 200 and len(payload_notag) == 0

        print("  --> PASS: Search correctly matched title, URL, notes, and tags; tag filtering and /api/tags verified")

        # Step 8: Update Bookmark, Notes & Favorite Toggling
        print("[Step 8/12] Update Bookmark, Notes, Favorite & Archive: PATCH /api/bookmarks/<id>...")
        # Brief pause to ensure updated_at timestamp increments past current second boundary
        time.sleep(1.05)
        patch_payload = {
            "notes": "Updated Documentation Notes",
            "is_favorite": True,
        }
        status, payload, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload=patch_payload
        )
        assert status == 200, f"Expected HTTP 200, got {status} ({payload})"
        assert isinstance(payload, dict), f"Expected dict response, got {type(payload)}"
        assert payload.get("notes") == "Updated Documentation Notes", (
            f"Expected updated notes, got {payload.get('notes')}"
        )
        assert payload.get("is_favorite") is True, (
            f"Expected is_favorite to be True, got {payload.get('is_favorite')}"
        )
        assert isinstance(payload.get("is_favorite"), bool), (
            f"Expected is_favorite to be boolean, got {type(payload.get('is_favorite'))}"
        )
        assert payload.get("archived") is False
        new_updated_at = payload.get("updated_at")
        assert new_updated_at and new_updated_at != updated_at, (
            f"Expected refreshed updated_at ({new_updated_at} != {updated_at})"
        )

        # Verify GET /api/bookmarks?favorites=true returns the bookmark with updated notes
        status_fav, payload_fav, _ = http_request(
            base_url, "GET", "/api/bookmarks?favorites=true"
        )
        assert status_fav == 200, f"Expected HTTP 200 for favorites query, got {status_fav}"
        assert isinstance(payload_fav, list) and len(payload_fav) == 1, (
            f"Expected 1 favorite bookmark, got {payload_fav}"
        )
        assert payload_fav[0].get("id") == bm_id, (
            f"Expected favorite bookmark ID {bm_id}, got {payload_fav[0].get('id')}"
        )
        assert payload_fav[0].get("notes") == "Updated Documentation Notes"
        assert payload_fav[0].get("is_favorite") is True

        # Verify search filtering matches updated notes text
        status_q_upd, payload_q_upd, _ = http_request(
            base_url, "GET", "/api/bookmarks?q=Updated"
        )
        assert status_q_upd == 200, f"Expected HTTP 200 for 'Updated' query, got {status_q_upd}"
        assert len(payload_q_upd) == 1
        assert payload_q_upd[0].get("id") == bm_id

        # Verify clearing notes via PATCH with empty string ""
        status_clear, payload_clear, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"notes": ""}
        )
        assert status_clear == 200, f"Expected HTTP 200 for clearing notes, got {status_clear}"
        assert payload_clear.get("notes") == "", f"Expected notes to be cleared to '', got {payload_clear.get('notes')}"

        # Verify cleared notes directly in sqlite3
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT notes FROM bookmarks WHERE id = ?", (bm_id,))
            row_clear = cursor.fetchone()
            assert row_clear is not None and row_clear[0] == "", (
                f"Expected empty string notes in sqlite3, got {row_clear}"
            )
        finally:
            conn.close()

        # Restore updated notes for subsequent verification
        status_restore, payload_restore, _ = http_request(
            base_url,
            "PATCH",
            f"/api/bookmarks/{bm_id}",
            payload={"notes": "Updated Documentation Notes"},
        )
        assert status_restore == 200, f"Expected HTTP 200 restoring notes, got {status_restore}"
        assert payload_restore.get("notes") == "Updated Documentation Notes"

        # Verify updating tags via PATCH
        status_patch_tags, payload_patch_tags, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"tags": ["python", "reference"]}
        )
        assert status_patch_tags == 200, f"Expected HTTP 200 updating tags, got {status_patch_tags}"
        assert payload_patch_tags.get("tags") == ["python", "reference"]

        # Verify /api/tags reflects updated tags
        _, payload_tags_updated, _ = http_request(base_url, "GET", "/api/tags")
        assert payload_tags_updated == {"tags": ["python", "reference"]}

        # Verify invalid notes rejected on PATCH
        status_bad_notes, payload_bad_notes, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"notes": 9999}
        )
        assert status_bad_notes == 400, f"Expected HTTP 400 for integer notes in PATCH, got {status_bad_notes}"

        # Verify invalid archived rejected on PATCH
        status_bad_patch_arch, _, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"archived": "invalid"}
        )
        assert status_bad_patch_arch == 400, f"Expected HTTP 400 for non-boolean archived in PATCH, got {status_bad_patch_arch}"

        # Verify PATCH updates archived boolean
        status_patch_arch, payload_patch_arch, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"archived": True}
        )
        assert status_patch_arch == 200
        assert payload_patch_arch.get("archived") is True
        assert isinstance(payload_patch_arch.get("archived"), bool)

        # Restore active status via PATCH
        status_patch_unarch, payload_patch_unarch, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"archived": False}
        )
        assert status_patch_unarch == 200
        assert payload_patch_unarch.get("archived") is False

        # Verify favorite toggling to False via PATCH
        status_unfav, payload_unfav, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"is_favorite": False}
        )
        assert status_unfav == 200, f"Expected HTTP 200, got {status_unfav}"
        assert payload_unfav.get("is_favorite") is False
        assert isinstance(payload_unfav.get("is_favorite"), bool)

        # Verify GET /api/bookmarks?favorites=true returns empty list after toggling to False
        status_empty_fav, payload_empty_fav, _ = http_request(
            base_url, "GET", "/api/bookmarks?favorites=true"
        )
        assert status_empty_fav == 200, f"Expected HTTP 200, got {status_empty_fav}"
        assert isinstance(payload_empty_fav, list) and len(payload_empty_fav) == 0, (
            f"Expected 0 favorite bookmarks after unfavoriting, got {payload_empty_fav}"
        )

        # Toggle favorite back to True via PATCH
        status_refav, payload_refav, _ = http_request(
            base_url, "PATCH", f"/api/bookmarks/{bm_id}", payload={"is_favorite": True}
        )
        assert status_refav == 200, f"Expected HTTP 200, got {status_refav}"
        assert payload_refav.get("is_favorite") is True
        assert isinstance(payload_refav.get("is_favorite"), bool)

        # Re-verify GET /api/bookmarks?favorites=true returns the bookmark again
        status_fav2, payload_fav2, _ = http_request(
            base_url, "GET", "/api/bookmarks?favorites=true"
        )
        assert status_fav2 == 200, f"Expected HTTP 200 for favorites query, got {status_fav2}"
        assert isinstance(payload_fav2, list) and len(payload_fav2) == 1, (
            f"Expected 1 favorite bookmark, got {payload_fav2}"
        )
        assert payload_fav2[0].get("id") == bm_id
        assert payload_fav2[0].get("is_favorite") is True
        assert payload_fav2[0].get("notes") == "Updated Documentation Notes"

        # Verify sqlite3 persistence directly
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, notes, is_favorite, archived FROM bookmarks WHERE id = ?", (bm_id,))
            row = cursor.fetchone()
            assert row is not None, f"Bookmark {bm_id} not found in sqlite3 database"
            assert row[1] == "Updated Documentation Notes", f"Expected notes in DB, got {row[1]}"
            assert row[2] == 1, f"Expected is_favorite=1 in database, got {row[2]}"
            assert row[3] == 0, f"Expected archived=0 in database, got {row[3]}"
        finally:
            conn.close()

        print(
            f"  --> PASS: Updated bookmark notes, verified clearing/restoring notes, favorite & archive toggling via PATCH; "
            f"updated_at refreshed to {new_updated_at}; favorites filter verified via GET"
        )

        # Step 8b: Archive & Restore Toggling Semantics
        print("[Step 8b] Archive & Restore Semantics: POST /api/bookmarks/<id>/archive & /restore, ?archived=...")
        time.sleep(1.05)
        # 1. Archive bookmark via dedicated endpoint
        status_arch, payload_arch, _ = http_request(base_url, "POST", f"/api/bookmarks/{bm_id}/archive")
        assert status_arch == 200, f"Expected HTTP 200 archiving bookmark, got {status_arch}"
        assert payload_arch.get("id") == bm_id, f"Expected id {bm_id}, got {payload_arch.get('id')}"
        assert payload_arch.get("archived") is True, f"Expected archived True, got {payload_arch.get('archived')}"
        assert isinstance(payload_arch.get("archived"), bool), (
            f"Expected archived to be boolean, got {type(payload_arch.get('archived'))}"
        )
        arch_updated_at = payload_arch.get("updated_at")
        assert arch_updated_at and arch_updated_at != new_updated_at, (
            f"Expected updated_at to refresh on archive: {arch_updated_at} vs {new_updated_at}"
        )

        # Direct SQLite inspection
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT archived FROM bookmarks WHERE id = ?", (bm_id,))
            row = cursor.fetchone()
            assert row is not None and row[0] == 1, f"Expected archived=1 in sqlite3, got {row}"
        finally:
            conn.close()

        # Idempotent archive: calling /archive again when already archived returns 200
        status_arch_idemp, payload_arch_idemp, _ = http_request(base_url, "POST", f"/api/bookmarks/{bm_id}/archive")
        assert status_arch_idemp == 200, f"Expected HTTP 200 on repeated archive, got {status_arch_idemp}"
        assert payload_arch_idemp.get("archived") is True

        # 2. Verify default GET /api/bookmarks returns 0 items (active only by default)
        status_unarch_list, payload_unarch_list, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status_unarch_list == 200
        assert isinstance(payload_unarch_list, list) and len(payload_unarch_list) == 0, (
            f"Expected default listing to exclude archived bookmark, got {payload_unarch_list}"
        )

        # 3. Verify explicit GET /api/bookmarks?archived=false returns 0 items
        status_false_list, payload_false_list, _ = http_request(base_url, "GET", "/api/bookmarks?archived=false")
        assert status_false_list == 200
        assert isinstance(payload_false_list, list) and len(payload_false_list) == 0, (
            f"Expected ?archived=false to return 0 items, got {payload_false_list}"
        )

        # 4. Verify explicit GET /api/bookmarks?archived=true returns the archived bookmark
        status_arch_list, payload_arch_list, _ = http_request(base_url, "GET", "/api/bookmarks?archived=true")
        assert status_arch_list == 200
        assert isinstance(payload_arch_list, list) and len(payload_arch_list) == 1, (
            f"Expected 1 item for ?archived=true, got {payload_arch_list}"
        )
        assert payload_arch_list[0].get("id") == bm_id
        assert payload_arch_list[0].get("archived") is True
        assert isinstance(payload_arch_list[0].get("archived"), bool)

        # 5. Verify explicit GET /api/bookmarks?archived=all returns the bookmark
        status_all_list, payload_all_list, _ = http_request(base_url, "GET", "/api/bookmarks?archived=all")
        assert status_all_list == 200
        assert isinstance(payload_all_list, list) and len(payload_all_list) == 1, (
            f"Expected 1 item for ?archived=all, got {payload_all_list}"
        )
        assert payload_all_list[0].get("id") == bm_id

        # 6. Verify combined archive filter with favorites filter
        # Since bm_id is favorited and archived: ?archived=true&favorites=true matches
        status_arch_fav, payload_arch_fav, _ = http_request(
            base_url, "GET", "/api/bookmarks?archived=true&favorites=true"
        )
        assert status_arch_fav == 200 and len(payload_arch_fav) == 1
        assert payload_arch_fav[0].get("id") == bm_id

        # ?archived=false&favorites=true should return 0 items
        status_arch_nonfav, payload_arch_nonfav, _ = http_request(
            base_url, "GET", "/api/bookmarks?archived=false&favorites=true"
        )
        assert status_arch_nonfav == 200 and len(payload_arch_nonfav) == 0

        # 7. Restore bookmark via dedicated endpoint
        time.sleep(1.05)
        status_rest, payload_rest, _ = http_request(base_url, "POST", f"/api/bookmarks/{bm_id}/restore")
        assert status_rest == 200, f"Expected HTTP 200 restoring bookmark, got {status_rest}"
        assert payload_rest.get("id") == bm_id
        assert payload_rest.get("archived") is False, f"Expected archived False after restore, got {payload_rest.get('archived')}"
        assert isinstance(payload_rest.get("archived"), bool), (
            f"Expected archived to be boolean, got {type(payload_rest.get('archived'))}"
        )
        rest_updated_at = payload_rest.get("updated_at")
        assert rest_updated_at and rest_updated_at != arch_updated_at, (
            f"Expected updated_at to refresh on restore: {rest_updated_at} vs {arch_updated_at}"
        )

        # Direct SQLite inspection
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT archived FROM bookmarks WHERE id = ?", (bm_id,))
            row = cursor.fetchone()
            assert row is not None and row[0] == 0, f"Expected archived=0 in sqlite3 after restore, got {row}"
        finally:
            conn.close()

        # Idempotent restore: calling /restore again when already active returns 200
        status_rest_idemp, payload_rest_idemp, _ = http_request(base_url, "POST", f"/api/bookmarks/{bm_id}/restore")
        assert status_rest_idemp == 200, f"Expected HTTP 200 on repeated restore, got {status_rest_idemp}"
        assert payload_rest_idemp.get("archived") is False

        # 8. Verify default GET /api/bookmarks now returns the bookmark again
        status_rest_list, payload_rest_list, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status_rest_list == 200
        assert isinstance(payload_rest_list, list) and len(payload_rest_list) == 1, (
            f"Expected default listing to include restored bookmark, got {payload_rest_list}"
        )
        assert payload_rest_list[0].get("id") == bm_id
        assert payload_rest_list[0].get("archived") is False

        # 9. Verify explicit GET /api/bookmarks?archived=false returns 1 item
        status_rest_false, payload_rest_false, _ = http_request(base_url, "GET", "/api/bookmarks?archived=false")
        assert status_rest_false == 200 and len(payload_rest_false) == 1

        # 10. Verify explicit GET /api/bookmarks?archived=true returns 0 items now
        status_rest_arch, payload_rest_arch, _ = http_request(base_url, "GET", "/api/bookmarks?archived=true")
        assert status_rest_arch == 200 and len(payload_rest_arch) == 0

        # 11. Verify 404 for non-existent archive/restore
        status_arch_404, err_arch_404, _ = http_request(base_url, "POST", "/api/bookmarks/99999/archive")
        assert status_arch_404 == 404
        assert isinstance(err_arch_404, dict) and "error" in err_arch_404

        status_rest_404, err_rest_404, _ = http_request(base_url, "POST", "/api/bookmarks/99999/restore")
        assert status_rest_404 == 404
        assert isinstance(err_rest_404, dict) and "error" in err_rest_404

        # 12. Verify 400 for invalid IDs on archive/restore
        status_arch_400, err_arch_400, _ = http_request(base_url, "POST", "/api/bookmarks/invalid_id/archive")
        assert status_arch_400 == 400
        assert isinstance(err_arch_400, dict) and "error" in err_arch_400

        status_rest_400, err_rest_400, _ = http_request(base_url, "POST", "/api/bookmarks/invalid_id/restore")
        assert status_rest_400 == 400
        assert isinstance(err_rest_400, dict) and "error" in err_rest_400

        print("  --> PASS: Archive and restore actions, 404/400 handling, SQLite persistence, and ?archived filtering verified")

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

        # Verify deletion in sqlite3
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM bookmarks WHERE id = ?", (bm_id,))
            assert cursor.fetchone() is None, f"Bookmark {bm_id} still exists in sqlite3"
        finally:
            conn.close()

        # Verify listing is now empty
        status_empty_list, payload_empty_list, _ = http_request(base_url, "GET", "/api/bookmarks")
        assert status_empty_list == 200
        assert isinstance(payload_empty_list, list) and len(payload_empty_list) == 0, (
            f"Expected empty list after deletion, got {payload_empty_list}"
        )
        print(f"  --> PASS: Successfully deleted bookmark {bm_id} and verified empty listing")

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
        assert b"filter-archived-btn" in body_root, "Expected filter-archived-btn in index.html"

        # CSS stylesheet
        status_css, _, body_css = http_request(base_url, "GET", "/style.css")
        assert status_css == 200, f"Expected HTTP 200 for /style.css, got {status_css}"
        assert len(body_css) > 0, "Expected non-empty response body for /style.css"
        assert b"card-notes" in body_css, "Expected 'card-notes' styling in style.css"
        assert b"filter-archived-btn" in body_css, "Expected filter-archived-btn styling in style.css"
        assert b"btn-archive" in body_css, "Expected btn-archive styling in style.css"

        # JS client script
        status_js, _, body_js = http_request(base_url, "GET", "/app.js")
        assert status_js == 200, f"Expected HTTP 200 for /app.js, got {status_js}"
        assert len(body_js) > 0, "Expected non-empty response body for /app.js"
        assert b"card-notes" in body_js, "Expected card-notes handling in app.js"
        assert b"btn-archive" in body_js, "Expected btn-archive handling in app.js"
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
