# Worker Operating Instructions

You are an automated software engineering worker executing a targeted task within an isolated Git worktree.

## Strict Operational Guardrails

1. **Assigned Workspace**: You MUST operate exclusively within the provided worktree directory: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/backend/att-1`. Never access or modify any files outside this directory.
2. **Allowed Paths**: You may ONLY create or modify files matching the following allowed path pattern(s):
- `examples/minilinks/app/**`
Modifying any out-of-scope files will result in an immediate rejection of your work.
3. **No Package Installation**: DO NOT install any packages or dependencies. Do NOT run `pip`, `npm`, `apt`, `brew`, or any other package manager.
4. **No Environment Mutation**: DO NOT alter or create `.venv`, do NOT modify `.agy-factory`, do NOT touch Herdr settings or sessions, and do NOT alter user/global configuration or authentication.
5. **No Version Control Manipulation**: DO NOT run `git commit`, `git push`, `git branch`, `git merge`, or `git worktree`. Git lifecycle, integration, and commits are owned exclusively by the factory orchestrator.
6. **Tool Usage — STRICTLY NO SHELL EXECUTION**:
   - You MUST use the `write_to_file` and `replace_file_content` tools to create and edit code.
   - When calling `write_to_file`, `TargetFile` MUST be the full absolute path: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/backend/att-1/<relative_path>`.
   - DO NOT call the `run_command` tool. Shell command execution is prohibited and will be denied automatically.
7. **Implementation Quality**: Follow the committed specification and API contract strictly. Ensure standard library compliance only (Python 3 stdlib, SQLite, vanilla HTML/CSS/JS).

## Task Description
Implement the is_favorite feature in the MiniLinks backend. In examples/minilinks/app/database.py: update SQLite schema to include 'is_favorite INTEGER DEFAULT 0' (with backward-compatible table migration adding the column via ALTER TABLE if missing), support favorites_only filter in get_all_bookmarks, support is_favorite in update_bookmark, and ensure row-to-dict returns 'is_favorite' as a Python boolean. In examples/minilinks/app/server.py: parse ?favorites=true in GET /api/bookmarks, parse is_favorite in PATCH /api/bookmarks/<id>, and ensure JSON response includes is_favorite.

### Reference Context File: `examples/minilinks/SPEC.md`
```markdown
# MiniLinks Product Specification

## 1. Executive Summary & Overview

**MiniLinks** is a zero-dependency, lightweight, single-user bookmark manager web application designed for local operation. It provides an intuitive, responsive web interface for saving, organizing, favoriting, searching, editing, and deleting bookmarks with associated notes and URLs. The application is backed by a robust, standard-library-only Python HTTP server and SQLite database storage.

### Core Architectural Principles
- **Zero Third-Party Dependencies**: Built strictly using the Python 3 standard library (`http.server`, `sqlite3`, `json`, `urllib`, `unittest`, `threading`, `pathlib`, `os`) and standard web technologies (vanilla HTML5, CSS3, and modern ES6+ JavaScript).
- **Process & Test Isolation**: Headless server instantiation with configurable host, ephemeral port binding (`port=0`), and isolated database paths to enable concurrent execution and automated testing without port collisions or file locks.
- **Contract Determinism**: Explicit REST API endpoints, strict schema validation, predictable HTTP status codes, and unambiguous data contracts.
- **Persistence Integrity**: Atomic, ACID-compliant persistence using SQLite with transactional operations and integrity constraints.
- **Directory Traversal Security**: Strict path sanitization for static file serving, preventing unauthorized access outside the designated web directory.

---

## 2. SQLite Database Schema

The database persists bookmarks in a single SQLite table named `bookmarks`.

### 2.1 Table Definition: `bookmarks`

```sql
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    notes TEXT DEFAULT '',
    is_favorite INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 2.2 Column Specifications

| Column Name | SQLite Type | Constraints | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique identifier generated sequentially by SQLite. | `1` |
| `title` | `TEXT` | `NOT NULL` | Human-readable title of the bookmark. Cannot be NULL or empty string. | `"Python Documentation"` |
| `url` | `TEXT` | `NOT NULL` | Destination web URL. Cannot be NULL or empty string. | `"https://docs.python.org/3/"` |
| `notes` | `TEXT` | `DEFAULT ''` | Optional user notes, tags, or description. Defaults to empty string if omitted. | `"Official Python 3 library reference"` |
| `is_favorite` | `INTEGER` | `DEFAULT 0` | Boolean flag indicating whether the bookmark is starred/favorited (`0` for false, `1` for true). Serialized as a native boolean (`true`/`false`) in JSON API payloads. | `0` (serialized as `false`) |
| `created_at`| `TEXT` | `NOT NULL` | ISO 8601 UTC timestamp recorded when the bookmark record is first inserted. | `"2026-09-23T00:00:00Z"` |
| `updated_at`| `TEXT` | `NOT NULL` | ISO 8601 UTC timestamp updated on initial creation and every subsequent modification. | `"2026-09-23T00:05:00Z"` |

### 2.3 Data Validation & Constraints
- `title`: Must be a non-empty string after whitespace stripping.
- `url`: Must be a non-empty string after whitespace stripping.
- `notes`: If not provided or `None`, defaults to an empty string `""`.
- `is_favorite`: Stored as SQLite `INTEGER` (`0` for `false`, `1` for `true`) with default `0`. In JSON API request and response payloads, it is represented and serialized as a native boolean (`true` or `false`). Non-boolean values in API payloads (such as strings or arbitrary numbers other than strict boolean deserialization) must be rejected with `400 Bad Request`.
- `created_at`: Set automatically at insert time; never mutated on updates.
- `updated_at`: Set automatically at insert time; updated to current ISO 8601 UTC timestamp on every `PATCH` modification.

### 2.4 Timestamp Standards
- Timestamps must follow ISO-8601 format in UTC: `YYYY-MM-DDTHH:MM:SSZ` or standard Python `datetime.now(datetime.timezone.utc).isoformat()`.

---

## 3. REST API Contract

All API endpoints exchange JSON payloads (`Content-Type: application/json; charset=utf-8`) unless serving static assets. Request bodies must contain valid JSON when a payload is expected.

### 3.1 `GET /health`
Verifies server health and responsiveness.

- **Request**:
  - Method: `GET`
  - Path: `/health`
  - Headers: None required
- **Response**:
  - Status: `200 OK`
  - Body:
    ```json
    {
      "status": "ok"
    }
    ```

---

### 3.2 `GET /api/bookmarks`
Retrieves a list of bookmarks, with optional query parameter filtering.

- **Request**:
  - Method: `GET`
  - Path: `/api/bookmarks`, `/api/bookmarks?q=<searchterm>`, `/api/bookmarks?favorites=true`, or `/api/bookmarks?favorites=true&q=<searchterm>`
  - Query Parameters:
    - `q` (optional, `string`): Search keyword. When provided, filters bookmarks where `title`, `url`, or `notes` contains the search term (case-insensitive substring match). When omitted or empty, search term filtering is not applied.
    - `favorites` (optional, `string`): Favorite filter flag. When set to `'true'` (case-insensitive, e.g. `?favorites=true`), returns only bookmarks marked as favorite (`is_favorite = 1`). When omitted, empty, or `'false'`, all bookmarks (matching `q` if present) are returned without favorite filtering.
- **Response**:
  - Status: `200 OK`
  - Body: JSON array of bookmark objects ordered by `id ASC` (or `created_at DESC`). Returns an empty array `[]` if no bookmarks match.
    ```json
    [
      {
        "id": 1,
        "title": "Python Documentation",
        "url": "https://docs.python.org/3/",
        "notes": "Official Python 3 library reference",
        "is_favorite": true,
        "created_at": "2026-09-23T00:00:00Z",
        "updated_at": "2026-09-23T00:00:00Z"
      },
      {
        "id": 2,
        "title": "SQLite Tutorial",
        "url": "https://www.sqlite.org/",
        "notes": "SQLite syntax and architecture",
        "is_favorite": false,
        "created_at": "2026-09-23T00:01:00Z",
        "updated_at": "2026-09-23T00:05:00Z"
      }
    ]
    ```

---

### 3.3 `POST /api/bookmarks`
Creates a new bookmark.

- **Request**:
  - Method: `POST`
  - Path: `/api/bookmarks`
  - Headers: `Content-Type: application/json`
  - Body:
    ```json
    {
      "title": "MDN Web Docs",
      "url": "https://developer.mozilla.org/",
      "notes": "Web standards and guides",
      "is_favorite": false
    }
    ```
    - `title` (required, `string`): Non-empty title.
    - `url` (required, `string`): Non-empty URL.
    - `notes` (optional, `string`): Optional notes (defaults to `""` if omitted).
    - `is_favorite` (optional, `boolean`): Optional favorite flag (defaults to `false` if omitted).
- **Success Response**:
  - Status: `201 Created`
  - Body: Complete bookmark object including generated `id`, `created_at`, `updated_at`, and `is_favorite`.
    ```json
    {
      "id": 3,
      "title": "MDN Web Docs",
      "url": "https://developer.mozilla.org/",
      "notes": "Web standards and guides",
      "is_favorite": false,
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:10:00Z"
    }
    ```
- **Error Responses**:
  - Status: `400 Bad Request`
  - Conditions: Missing request body, invalid JSON syntax, missing `title`, empty/whitespace-only `title`, missing `url`, empty/whitespace-only `url`, or fields not of expected type (including non-boolean `is_favorite` when provided).
  - Body:
    ```json
    {
      "error": "Both 'title' and 'url' are required non-empty strings"
    }
    ```

---

### 3.4 `PATCH /api/bookmarks/<id>`
Partially updates an existing bookmark's `title`, `url`, `notes`, `is_favorite`, or any combination thereof.

- **Request**:
  - Method: `PATCH`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
  - Headers: `Content-Type: application/json`
  - Body: JSON containing one or more fields to update:
    ```json
    {
      "is_favorite": true
    }
    ```
    or
    ```json
    {
      "title": "MDN Web Docs - Updated",
      "url": "https://developer.mozilla.org/en-US/",
      "is_favorite": true
    }
    ```
    - Updatable fields:
      - `title` (`string`, optional): Non-empty string after stripping whitespace.
      - `url` (`string`, optional): Non-empty string after stripping whitespace.
      - `notes` (`string`, optional): String notes value.
      - `is_favorite` (`boolean`, optional): Boolean value (`true` or `false`) to update favorite/starred status.
- **Success Response**:
  - Status: `200 OK`
  - Body: Complete updated bookmark object with refreshed `updated_at` timestamp.
    ```json
    {
      "id": 3,
      "title": "MDN Web Docs - Updated",
      "url": "https://developer.mozilla.org/en-US/",
      "notes": "Web standards and guides",
      "is_favorite": true,
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:15:00Z"
    }
    ```
- **Error Responses**:
  - Status: `404 Not Found`
    - Condition: Bookmark with specified `<id>` does not exist.
    - Body:
      ```json
      {
        "error": "Bookmark not found"
      }
      ```
  - Status: `400 Bad Request`
    - Conditions: Non-integer `<id>` in URL, malformed JSON body, empty update payload (no updatable fields provided), empty or whitespace-only `title` or `url` when provided, or invalid field types (e.g., non-boolean `is_favorite`).
    - Body:
      ```json
      {
        "error": "Invalid update payload"
      }
      ```

---

### 3.5 `DELETE /api/bookmarks/<id>`
Deletes a bookmark by ID.

- **Request**:
  - Method: `DELETE`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
- **Success Response**:
  - Status: `200 OK`
  - Body:
    ```json
    {
      "status": "deleted",
      "id": 3
    }
    ```
- **Error Responses**:
  - Status: `404 Not Found`
    - Condition: Bookmark with specified `<id>` does not exist.
    - Body:
      ```json
      {
        "error": "Bookmark not found"
      }
      ```
  - Status: `400 Bad Request`
    - Condition: Non-integer `<id>` in URL.
    - Body:
      ```json
      {
        "error": "Invalid bookmark ID"
      }
      ```

---

## 4. Static File Serving Specification

The backend server serves static front-end assets located in the `web/` directory:
- `/` or `/index.html` $\rightarrow$ `web/index.html` (`Content-Type: text/html; charset=utf-8`)
- `/style.css` $\rightarrow$ `web/style.css` (`Content-Type: text/css; charset=utf-8`)
- `/app.js` $\rightarrow$ `web/app.js` (`Content-Type: application/javascript; charset=utf-8`)

### Security & Directory Traversal Protection
- Static file paths must be resolved strictly relative to the designated `web/` directory.
- Directory traversal attacks (such as `../`, `..%2F`, `..\`, absolute paths, or symbolic links escaping `web/`) must be detected and rejected with `403 Forbidden` or `404 Not Found`.
- Non-existent static files within `web/` must return `404 Not Found`.

---

## 5. Python Backend Architecture & Programmatic Interface

### 5.1 Module Structure
- `app/database.py`: Encapsulates SQLite connection management, table initialization, and CRUD query functions (`init_db`, `get_bookmarks(q=None, favorites_only=False)`, `create_bookmark(title, url, notes, is_favorite=False)`, `update_bookmark(id, title=None, url=None, notes=None, is_favorite=None)`, `delete_bookmark(id)`).
- `app/server.py`: Implements custom `http.server.BaseHTTPRequestHandler` routing, request dispatching, JSON serialization and deserialization (converting SQLite integer `0`/`1` to JSON boolean `false`/`true`), query parameter parsing (supporting `q` search term and `favorites=true` filter), static file delivery, and the programmatic factory function `create_server`.

### 5.2 Server Factory Interface: `create_server`

```python
def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    db_path: str = "minilinks.db"
) -> http.server.HTTPServer:
    """
    Initializes the SQLite database at `db_path`, instantiates an HTTPServer
    bound to (host, port), and starts listening inside a background daemon thread.

    Parameters:
        host (str): Hostname or IP to bind (default: '127.0.0.1').
        port (int): Port number (default: 0 for OS-assigned ephemeral port).
        db_path (str): File system path to the SQLite database.

    Returns:
        http.server.HTTPServer:
            The running HTTPServer instance. The server runs in a daemon thread,
            exposes `server_port` / `server_address` (resolving the ephemeral port),
            and supports clean shutdown via `server.shutdown()` and `server.server_close()`.
    """
```

### 5.3 Lifecycle & Teardown Requirements
- **Daemon Thread**: The background thread executing `server.serve_forever()` must be configured with `daemon=True` so it does not prevent Python process termination.
- **Ephemeral Port Resolution**: When `port=0` is supplied, callers can retrieve the OS-assigned port via `server.server_port` or `server.server_address[1]`.
- **Clean Shutdown**: Calling `server.shutdown()` followed by `server.server_close()` stops the server loop and releases socket resources immediately without deadlocks or lingering threads.

---

## 6. Frontend Architecture & UI/UX Requirements

The frontend lives in `web/` and consists of three standard files:
- `web/index.html`: Semantic HTML structure.
- `web/style.css`: Clean, modern, responsive CSS styling.
- `web/app.js`: Vanilla JavaScript client logic communicating with the REST API.

### 6.1 Layout & Components
- **Header**: MiniLinks title/branding, search bar, filter bar, and an operational status/notification banner.
- **Search Bar**: Input field (`id="search-input"`) with real-time or debounced query filtering that triggers `GET /api/bookmarks?q=<term>` (preserving the active favorites filter state) and updates the displayed cards list.
- **Filter Bar & Favorites Toggle**:
  - Filter control bar containing the favorites filter toggle button (`id="filter-favorites-btn"`).
  - Toggles between showing all bookmarks and showing only favorited bookmarks.
  - When favorites filter is active, triggers `GET /api/bookmarks?favorites=true` (combining with `q` search term if present).
  - Provides visual active indicator (e.g. active CSS class, highlighted styling, and star icon state: `★ Favorites` active vs `☆ Favorites` inactive).
- **Bookmark Creation Form**:
  - Input for `title` (required text input, `id="bookmark-title"`).
  - Input for `url` (required URL/text input, `id="bookmark-url"`).
  - Input or textarea for `notes` (optional text, `id="bookmark-notes"`).
  - Submit button (`id="bookmark-submit-btn"`) to create the bookmark via `POST /api/bookmarks`.
- **Bookmarks List / Cards Grid**:
  - Container (`id="bookmarks-list"`) rendering responsive bookmark cards.
  - Displays an empty state message if no bookmarks exist or no bookmarks match the search/filter criteria.

### 6.2 Bookmark Card Elements & Interactions
Each bookmark card rendered must display:
- **Favorite / Star Toggle Button**: Star button (`id="favorite-btn-<id>"` or class `favorite-toggle-btn`) displaying a filled star `★` if favorited (`is_favorite: true`) or an outlined star `☆` if not favorited (`is_favorite: false`).
  - Clicking the star button dispatches `PATCH /api/bookmarks/<id>` with payload `{"is_favorite": !currentStatus}`.
  - On receiving `200 OK`, immediately updates the star icon (`★` $\leftrightarrow$ `☆`), updates the card's internal state, and if the favorites filter is currently active and the item was unfavorited, removes or hides the card from the view.
- **Title**: Formatted title displaying the bookmark name, linking directly to the URL (`target="_blank"`, `rel="noopener noreferrer"`).
- **URL**: Visible destination URL with clean truncation if long.
- **Notes**: Formatted notes block if notes are present.
- **Timestamps**: Display created and/or updated timestamp.
- **Action Controls**:
  - **Star Button**: Inline toggle for favorite status.
  - **Edit Button**: Enables editing title, url, and notes (inline form or modal/prompt) and dispatches `PATCH /api/bookmarks/<id>`.
  - **Delete Button**: Dispatches `DELETE /api/bookmarks/<id>` with immediate removal from the DOM and success confirmation.
- **Error & Status Notifications**: Clear visual feedback (banner or toast) on network failures, validation errors, and successful operations.

### 6.3 Responsive Design
- Mobile-first, responsive CSS (Flexbox / CSS Grid).
- Adapts smoothly from narrow mobile screens (single-column card stack) to wide desktop displays (multi-column grid).

---

## 7. Testing Requirements & Test Harness

Testing is implemented strictly using Python's standard library `unittest`, `urllib.request`, `sqlite3`, and `threading`. Tests must not depend on any third-party packages.

### 7.1 Unit & Integration Test Suites in `tests/`

#### 7.1.1 `tests/test_api.py`
Validates all HTTP API endpoints against a live server running on an ephemeral port with an isolated temporary SQLite database:
1. Server bootstrap and `GET /health` responding with `200 OK` and `{"status": "ok"}`.
2. Initial bookmark listing `GET /api/bookmarks` returning an empty array `[]`.
3. Creating bookmarks via `POST /api/bookmarks` with valid payloads (title, url, notes) and verifying `201 Created` with default `is_favorite: false`.
4. Creating bookmarks with invalid payloads (missing title, empty url, non-string values) verifying `400 Bad Request`.
5. Search filtering via `GET /api/bookmarks?q=<searchterm>` verifying matching by title, url, or notes, and verifying empty results for non-matching queries.
6. Updating bookmarks via `PATCH /api/bookmarks/<id>` for title, url, and notes, verifying `200 OK` and updated fields.
7. Toggling favorite status via `PATCH /api/bookmarks/<id>` with `{"is_favorite": true}` and `{"is_favorite": false}`, verifying `200 OK` and boolean serialization.
8. Favorite filtering via `GET /api/bookmarks?favorites=true` verifying only favorited bookmarks are returned, and combining `favorites=true` with search query `q`.
9. Error responses: verifying `400 Bad Request` on malformed JSON, invalid payload, or non-boolean `is_favorite`, and `404 Not Found` for non-existent IDs on `PATCH` and `DELETE`.
10. Deleting bookmarks via `DELETE /api/bookmarks/<id>` verifying `200 OK` and subsequent 404 response on repeated deletion.
11. Static file delivery: verifying retrieval of `/`, `/index.html`, `/style.css`, and `/app.js` with correct MIME types.
12. Directory traversal protection: verifying requests with `../` or encoded traversal paths are rejected with `403` or `404`.

#### 7.1.2 `tests/test_persistence.py`
Validates SQLite persistence across server lifecycle restarts:
1. Starts Server 1 on an ephemeral port with a temporary `db_path`.
2. Inserts bookmarks into Server 1 via `POST /api/bookmarks` and toggles favorite status via `PATCH /api/bookmarks/<id>`.
3. Shuts down Server 1 cleanly (`server.shutdown()`, `server.server_close()`).
4. Verifies database file integrity directly using the `sqlite3` module, including `is_favorite` stored as `0` or `1`.
5. Starts Server 2 pointing to the same `db_path` on a new ephemeral port.
6. Verifies all previously created bookmarks, updated notes, favorite status, and timestamps persist and are queryable via `GET /api/bookmarks`.
7. Shuts down Server 2 and cleans up temporary database files.

---

### 7.2 Standalone 12-Step Smoke Test: `scripts/smoke_test.py`

`scripts/smoke_test.py` is a standalone executable Python script that executes an end-to-end verification scenario against an ephemeral server instance. It prints deterministic progress logs for each step and exits with status code `0` on total success or non-zero on any assertion failure.

#### The 12 Deterministic Steps:
1. **Step 1 - Server Bootstrap**: Start `create_server(host='127.0.0.1', port=0, db_path=temp_db)` on an ephemeral port; acquire bound port.
2. **Step 2 - Health Check**: Send `GET /health`; assert HTTP 200 and payload `{"status": "ok"}`.
3. **Step 3 - Initial Empty State**: Send `GET /api/bookmarks`; assert HTTP 200 and payload is an empty list `[]`.
4. **Step 4 - Create Bookmark (Valid)**: Send `POST /api/bookmarks` with `{"title": "Python Docs", "url": "https://docs.python.org", "notes": "Official Docs"}`; assert HTTP 201, `id` is positive integer, `is_favorite` defaults to `False`, fields match, and timestamps are populated.
5. **Step 5 - Create Bookmark Validation Error**: Send `POST /api/bookmarks` with invalid payload `{"title": ""}`; assert HTTP 400.
6. **Step 6 - Verify Bookmark Listing**: Send `GET /api/bookmarks`; assert HTTP 200 and list contains exactly 1 bookmark matching Step 4.
7. **Step 7 - Search Filtering**: Send `GET /api/bookmarks?q=Python`; assert HTTP 200 with 1 result. Send `GET /api/bookmarks?q=NonExistentTerm`; assert HTTP 200 with 0 results.
8. **Step 8 - Update Bookmark & Favorite**: Send `PATCH /api/bookmarks/<id>` with `{"notes": "Updated Documentation Notes", "is_favorite": true}`; assert HTTP 200, notes updated, `is_favorite` is `True`, `updated_at` updated. Also verify `GET /api/bookmarks?favorites=true` returns the bookmark.
9. **Step 9 - Update Non-Existent Bookmark**: Send `PATCH /api/bookmarks/99999` with `{"notes": "Ghost"}`; assert HTTP 404.
10. **Step 10 - Delete Bookmark**: Send `DELETE /api/bookmarks/<id>`; assert HTTP 200 and payload `{"status": "deleted", "id": <id>}`.
11. **Step 11 - Delete Non-Existent Bookmark**: Send `DELETE /api/bookmarks/99999`; assert HTTP 404.
12. **Step 12 - Verify Static Asset Delivery**: Send `GET /`, `GET /style.css`, `GET /app.js`; assert HTTP 200 for all three with appropriate non-empty responses.

*Cleanup*: After Step 12 completes, shut down the server thread and remove temporary database files.

---

## 8. Repository Layout & File Mapping

```
examples/minilinks/
├── SPEC.md                    # Complete MiniLinks product & architectural specification (this document)
├── app/
│   ├── __init__.py            # Python package marker
│   ├── database.py            # SQLite schema initialization and query operations
│   └── server.py              # HTTP request handler, routing, and create_server factory
├── web/
│   ├── index.html             # Responsive bookmark manager HTML interface
│   ├── style.css              # Modern responsive CSS styling
│   └── app.js                 # Vanilla JavaScript API client and DOM management
├── tests/
│   ├── __init__.py            # Test package marker
│   ├── test_api.py            # unittest suite for REST API endpoints & static files
│   └── test_persistence.py    # unittest suite for database restart persistence
└── scripts/
    └── smoke_test.py          # Standalone 12-step deterministic smoke verification
```

---

## 9. Deterministic Quality Gates & Verification Matrix

Before code is accepted or merged, the following automated checks must pass:
1. **Compilation Check**: `python3 -m compileall app tests scripts` passes with zero syntax errors.
2. **Unit Test Suite**: `python3 -m unittest discover -s tests -p "test_*.py"` completes with 100% passing tests.
3. **Smoke Test Execution**: `python3 scripts/smoke_test.py` completes all 12 steps and exits with status 0.

```

### Required TargetFile Paths to Create via write_to_file:
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/backend/att-1/examples/minilinks/app/database.py`
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/backend/att-1/examples/minilinks/app/server.py`


## Required Structured Output
You must return a valid JSON object matching the worker result schema:
```json
{
  "task_id": "backend",
  "status": "COMPLETED",
  "summary": "<clear summary of what was implemented>",
  "changed_files": ["<list of relative paths created or modified>"],
  "notes": "<optional design notes or considerations>"
}
```
