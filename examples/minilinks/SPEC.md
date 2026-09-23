# MiniLinks Product Specification

## 1. Executive Summary & Overview

**MiniLinks** is a zero-dependency, lightweight, single-user bookmark manager web application designed for local operation. It provides an intuitive, responsive web interface for saving, organizing, favoriting, searching, editing, and deleting bookmarks with associated notes and URLs. The application is backed by a robust, standard-library-only Python HTTP server and SQLite database storage.

### Core Architectural Principles
- **Zero Third-Party Dependencies**: Built strictly using the Python 3 standard library (`http.server`, `sqlite3`, `json`, `urllib`, `unittest`, `threading`, `pathlib`, `os`) and standard web technologies (vanilla HTML5, CSS3, and modern ES6+ JavaScript).
- **Process & Test Isolation**: Headless server instantiation with configurable host, ephemeral port binding (`port=0`), and isolated database paths to enable concurrent execution and automated testing without port collisions or file locks.
- **Contract Determinism**: Explicit REST API endpoints, strict schema validation, predictable HTTP status codes, and unambiguous data contracts.
- **Persistence Integrity**: Atomic, ACID-compliant persistence using SQLite with transactional operations and integrity constraints.
- **Directory Traversal Security**: Strict path sanitization for static file serving, preventing unauthorized access outside the designated web directory.

### Key Feature Set
- **Bookmark Management**: Create, view, edit, and delete web bookmarks with validated titles and URLs.
- **Optional Bookmark Notes**: Attach optional multiline notes, descriptions, or tags to bookmarks, persisted in SQLite and fully manageable via REST API and frontend UI.
- **Favorite / Star Pinning**: Fast toggle mechanism to favorite bookmarks and filter the dashboard to display only favorited items.
- **Full-Text Substring Search**: Real-time debounced search filtering bookmarks across title, URL, and notes text simultaneously.
- **Modal Editing**: In-place editing modal enabling seamless updates to title, destination URL, and notes with instant DOM synchronization.

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
    tags TEXT DEFAULT '[]',
    is_favorite INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 2.2 Column Specifications

| Column Name | SQLite Type | Constraints | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique identifier generated sequentially by SQLite. | `1` |
| `title` | `TEXT` | `NOT NULL` | Human-readable title of the bookmark. Cannot be NULL or empty string. | `"Python Documentation"` |
| `url` | `TEXT` | `NOT NULL` | Destination web URL. Must start with `http://` or `https://`. Cannot be NULL or empty string. | `"https://docs.python.org/3/"` |
| `notes` | `TEXT` | `DEFAULT ''` | Optional user notes, descriptions, or annotations. Stored as `TEXT DEFAULT ''`. Always serialized as a string in JSON payloads (`""` when empty). | `"Official Python 3 library reference"` |
| `tags` | `TEXT` | `DEFAULT '[]'` | JSON-serialized array of user-assigned textual tags. Always serialized as a list of strings (`[]` when empty). | `["python", "docs"]` |
| `is_favorite` | `INTEGER` | `DEFAULT 0` | Boolean flag indicating whether the bookmark is starred/favorited (`0` for false, `1` for true). Serialized as a native boolean (`true`/`false`) in JSON API payloads. | `0` (serialized as `false`) |
| `archived` | `INTEGER` | `DEFAULT 0` | Boolean flag indicating whether the bookmark is archived (`0` for active/false, `1` for archived/true). Serialized as a native boolean (`true`/`false`) in JSON API payloads. | `0` (serialized as `false`) |
| `created_at`| `TEXT` | `NOT NULL` | ISO 8601 UTC timestamp recorded when the bookmark record is first inserted. | `"2026-09-23T00:00:00Z"` |
| `updated_at`| `TEXT` | `NOT NULL` | ISO 8601 UTC timestamp updated on initial creation and every subsequent modification. | `"2026-09-23T00:05:00Z"` |

### 2.3 Data Validation & Constraints
- `title`: Must be a non-empty string after whitespace stripping. Rejects empty strings, whitespace-only strings, or non-string types with `400 Bad Request`.
- `url`: Must be a non-empty string after whitespace stripping, beginning with `http://` or `https://` and possessing a valid network location (hostname). Rejects malformed URLs with `400 Bad Request`.
- `notes`: Optional string attribute.
  - If omitted in API request payloads or explicitly passed as `null` / `None`, it defaults to an empty string `""`.
  - When provided, it must be a string. Non-string types (e.g., numbers, booleans, arrays, objects) must be rejected with `400 Bad Request`.
  - Supports arbitrary multiline text, newlines (`\n`), code snippets, URLs, markdown-like syntax, and special characters.
  - Stored in SQLite as `TEXT DEFAULT ''`. In all API responses, it is serialized as a native JSON string (`""` when empty, never `null` or omitted).
- `tags`: Optional list of strings attribute.
  - If omitted in API request payloads or explicitly passed as `null` / `None`, it defaults to an empty array `[]`.
  - When provided, it must be an array of strings. Non-array types or arrays containing non-string items must be rejected with `400 Bad Request`.
  - Tags are stripped of leading/trailing whitespace, and empty strings are pruned. Duplicate tags within the same bookmark are deduplicated while preserving order.
  - Stored in SQLite as a JSON array string `TEXT DEFAULT '[]'`. In all API responses, it is serialized as a native JSON array of strings (`[]` when empty).
- `is_favorite`: Stored as SQLite `INTEGER` (`0` for `false`, `1` for `true`) with default `0`. In JSON API request and response payloads, it is represented and serialized as a native boolean (`true` or `false`). Non-boolean values in API payloads (such as strings or arbitrary numbers other than strict boolean deserialization) must be rejected with `400 Bad Request`.
- `created_at`: Set automatically at insert time in ISO 8601 UTC format (`YYYY-MM-DDTHH:MM:SSZ`); never mutated on updates.
- `updated_at`: Set automatically at insert time; updated to the current ISO 8601 UTC timestamp on every `PATCH` modification.

### 2.4 Timestamp Standards
- Timestamps must follow ISO-8601 format in UTC: `YYYY-MM-DDTHH:MM:SSZ` generated via Python `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.

### 2.5 Optional Bookmark Notes Attribute Specification (`notes`)

The `notes` attribute provides user-authored context, annotations, tags, or detailed descriptions for a bookmark:

1. **Storage Representation**:
   - Column definition: `notes TEXT DEFAULT ''`.
   - SQLite guarantees backward compatibility: if existing databases contain `NULL` in legacy records, database query utilities coalesce `NULL` to an empty string `""` (`row["notes"] if row["notes"] is not None else ""`).
2. **Payload Serialization**:
   - Every bookmark dictionary serialized to JSON contains the key `"notes"` mapping to a string.
   - Example with notes: `"notes": "API reference and quick start guide"`.
   - Example without notes: `"notes": ""`.
   - It is never returned as `null` or excluded from the response payload.
3. **Creation Semantics**:
   - In `POST /api/bookmarks`, `notes` is entirely optional.
   - If excluded from the payload: defaults to `""`.
   - If explicitly provided as `null` (`None` in Python): defaults to `""`.
   - If provided as a string: preserved exactly as supplied (whitespace stripped or preserved according to user input).
   - If provided as non-string type: rejected with `400 Bad Request`.
4. **Update Semantics**:
   - In `PATCH /api/bookmarks/<id>`, `notes` can be updated independently or alongside other fields.
   - Updating notes replaces the previous notes string with the newly supplied string.
   - Supplying an empty string (`"notes": ""`) clears existing notes.
   - If provided as non-string type: rejected with `400 Bad Request`.
5. **Search Indexing**:
   - Substring search queries (`GET /api/bookmarks?q=<term>`) examine the `notes` column using case-insensitive search (`instr(LOWER(COALESCE(notes, '')), LOWER(?)) > 0`).

### 2.6 Optional Bookmark Tags Attribute Specification (`tags`)

The `tags` attribute provides lightweight categorical labeling for bookmarks:

1. **Storage Representation**:
   - Column definition: `tags TEXT DEFAULT '[]'`.
   - Tags are stored as a JSON-encoded array of strings.
   - Backward compatibility: older databases without `tags` are automatically migrated via `ALTER TABLE bookmarks ADD COLUMN tags TEXT DEFAULT '[]'`.
2. **Payload Serialization**:
   - Every bookmark dictionary serialized to JSON contains the key `"tags"` mapping to a list of strings.
   - Example with tags: `"tags": ["development", "python"]`.
   - Example without tags: `"tags": []`.
   - Never returned as `null` or excluded from the response payload.
3. **Creation Semantics**:
   - In `POST /api/bookmarks`, `tags` is optional.
   - Defaults to `[]` when omitted or `null`.
   - When supplied, must be an array of strings. Elements are trimmed, non-empty, and deduplicated preserving order.
   - Rejects non-array or array containing non-strings with `400 Bad Request`.
4. **Update Semantics**:
   - In `PATCH /api/bookmarks/<id>`, `tags` can be updated independently or alongside other fields.
   - Supplying an empty array (`"tags": []`) clears all tags.
   - Rejects non-array or array containing non-strings with `400 Bad Request`.
5. **Tag Filtering & Tag Query Endpoint**:
   - `GET /api/bookmarks?tag=<tag>` filters bookmarks that contain `<tag>` (case-insensitive).
   - `GET /api/tags` returns a list of all unique tags used across all bookmarks (`{"tags": [...]}`).

### 2.7 Optional Bookmark Archived Attribute Specification (`archived`)

The `archived` attribute provides soft-archival capabilities for bookmarks:

1. **Storage Representation**:
   - Column definition: `archived INTEGER DEFAULT 0`.
   - Backward compatibility: older databases without `archived` are automatically migrated via `ALTER TABLE bookmarks ADD COLUMN archived INTEGER DEFAULT 0`.
2. **Payload Serialization**:
   - Every bookmark dictionary serialized to JSON contains the key `"archived"` mapping to a boolean (`false` for active, `true` for archived).
   - Example active: `"archived": false`.
   - Example archived: `"archived": true`.
   - Never returned as `null` or excluded from the response payload.
3. **Creation Semantics**:
   - In `POST /api/bookmarks`, `archived` is optional, defaulting to `false`.
   - When provided, must be a native boolean. Non-boolean values are rejected with `400 Bad Request`.
4. **Update Semantics**:
   - In `PATCH /api/bookmarks/<id>`, `archived` can be updated directly via boolean.
   - Dedicated endpoints `POST /api/bookmarks/<id>/archive` and `POST /api/bookmarks/<id>/restore` provide convenient toggle actions.
5. **Archive Filtering**:
   - `GET /api/bookmarks`: By default (or with `?archived=false`), only unarchived bookmarks (`archived = 0`) are returned.
   - `GET /api/bookmarks?archived=true`: Returns only archived bookmarks (`archived = 1`).
   - `GET /api/bookmarks?archived=all`: Returns all bookmarks regardless of archive status.

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
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body:
    ```json
    {
      "status": "ok"
    }
    ```

---

### 3.2 `GET /api/bookmarks`
Retrieves a list of bookmarks, with optional query parameter filtering by search term (`q`) and favorite status (`favorites`).

- **Request**:
  - Method: `GET`
  - Path: `/api/bookmarks`, `/api/bookmarks?q=<term>`, `/api/bookmarks?favorites=true`, `/api/bookmarks?archived=true`, or `/api/bookmarks?archived=all`
  - Query Parameters:
    - `q` (optional, `string`): Search keyword. When provided and non-empty, filters bookmarks where `title`, `url`, or `notes` contains the search term (case-insensitive substring match). When omitted or empty/whitespace-only, search filtering is not applied.
    - `favorites` (optional, `string`): Favorite filter flag. When set to `'true'` (case-insensitive, e.g. `?favorites=true`), returns only bookmarks marked as favorite (`is_favorite = 1`). When omitted, empty, or `'false'`, all bookmarks (matching other filters) are returned without favorite filtering.
    - `archived` (optional, `string`): Archive filter flag. When omitted, empty, or `'false'`, returns only active, non-archived bookmarks (`archived = 0`). When set to `'true'` (e.g. `?archived=true`), returns only archived bookmarks (`archived = 1`). When set to `'all'` (e.g. `?archived=all`), returns both active and archived bookmarks.
- **Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: JSON array of bookmark objects ordered by `id ASC`. Every bookmark object includes `notes` as a string (`""` when empty). Returns an empty array `[]` if no bookmarks match.
    ```json
    [
      {
        "id": 1,
        "title": "Python Documentation",
        "url": "https://docs.python.org/3/",
        "notes": "Official Python 3 library reference and tutorial",
        "is_favorite": true,
        "created_at": "2026-09-23T00:00:00Z",
        "updated_at": "2026-09-23T00:00:00Z"
      },
      {
        "id": 2,
        "title": "SQLite Tutorial",
        "url": "https://www.sqlite.org/",
        "notes": "",
        "is_favorite": false,
        "created_at": "2026-09-23T00:01:00Z",
        "updated_at": "2026-09-23T00:05:00Z"
      }
    ]
    ```

---

### 3.3 `GET /api/bookmarks/<id>`
Retrieves a single bookmark by its unique ID.

- **Request**:
  - Method: `GET`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete bookmark object including `notes` string.
    ```json
    {
      "id": 1,
      "title": "Python Documentation",
      "url": "https://docs.python.org/3/",
      "notes": "Official Python 3 library reference and tutorial",
      "is_favorite": true,
      "created_at": "2026-09-23T00:00:00Z",
      "updated_at": "2026-09-23T00:00:00Z"
    }
    ```
- **Error Responses**:
  - Status: `404 Not Found`
    - Condition: Bookmark with specified `<id>` does not exist.
    - Body: `{"error": "Bookmark not found"}`
  - Status: `400 Bad Request`
    - Condition: Non-integer or non-positive `<id>` in URL path.
    - Body: `{"error": "Invalid bookmark ID"}`

---

### 3.4 `POST /api/bookmarks`
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
      "notes": "Web standards, HTML, CSS, and JavaScript guides",
      "is_favorite": false
    }
    ```
    - `title` (required, `string`): Non-empty string after trimming whitespace.
    - `url` (required, `string`): Non-empty URL string starting with `http://` or `https://` with valid hostname.
    - `notes` (optional, `string`): Optional user notes or annotations. If omitted or passed as `null`, defaults to `""`. If provided as a non-string type (e.g., number, boolean, array, object), rejected with `400 Bad Request`.
    - `is_favorite` (optional, `boolean`): Optional favorite flag (defaults to `false` if omitted). If provided as non-boolean, rejected with `400 Bad Request`.
- **Success Response**:
  - Status: `201 Created`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete bookmark object including generated `id`, `created_at`, `updated_at`, `is_favorite`, and `notes`.
    ```json
    {
      "id": 3,
      "title": "MDN Web Docs",
      "url": "https://developer.mozilla.org/",
      "notes": "Web standards, HTML, CSS, and JavaScript guides",
      "is_favorite": false,
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:10:00Z"
    }
    ```
- **Error Responses**:
  - Status: `400 Bad Request`
    - Conditions:
      - Missing request body or empty payload.
      - Malformed JSON syntax.
      - JSON body is not a JSON object (e.g., array or primitive).
      - Missing, empty, or whitespace-only `title` or `url`.
      - Invalid URL format (missing scheme `http://`/`https://` or host).
      - `notes` is provided but is not a string (e.g. `{"notes": 123}`).
      - `is_favorite` is provided but is not a boolean (e.g. `{"is_favorite": "true"}`).
    - Body Examples:
      ```json
      {
        "error": "Both 'title' and 'url' are required non-empty strings"
      }
      ```
      ```json
      {
        "error": "Notes must be a string if provided"
      }
      ```
      ```json
      {
        "error": "is_favorite must be a boolean if provided"
      }
      ```

---

### 3.5 `PATCH /api/bookmarks/<id>`
Partially updates an existing bookmark's `title`, `url`, `notes`, `is_favorite`, or any combination thereof.

- **Request**:
  - Method: `PATCH`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
  - Headers: `Content-Type: application/json`
  - Body: JSON object containing one or more fields to update:
    ```json
    {
      "notes": "Updated research notes on CSS Grid"
    }
    ```
    or
    ```json
    {
      "title": "MDN Web Docs - Updated",
      "notes": "Updated documentation notes",
      "is_favorite": true
    }
    ```
    or (clearing notes):
    ```json
    {
      "notes": ""
    }
    ```
    - Updatable fields:
      - `title` (`string`, optional): Non-empty string after stripping whitespace.
      - `url` (`string`, optional): Non-empty valid URL string starting with `http://` or `https://`.
       - `notes` (`string`, optional): Updated notes text string. Supplying `""` clears existing notes. Must be a string if provided; non-string types rejected with `400 Bad Request`.
       - `is_favorite` (`boolean`, optional): Native boolean (`true` or `false`) to update favorite status. Non-boolean types rejected with `400 Bad Request`.
       - `archived` (`boolean`, optional): Native boolean (`true` or `false`) to update archive status. Non-boolean types rejected with `400 Bad Request`.
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete updated bookmark object with refreshed `updated_at` timestamp.
    ```json
    {
      "id": 3,
      "title": "MDN Web Docs - Updated",
      "url": "https://developer.mozilla.org/",
      "notes": "Updated documentation notes",
      "is_favorite": true,
      "archived": false,
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:15:00Z"
    }
    ```
- **Error Responses**:
  - Status: `404 Not Found`
    - Condition: Bookmark with specified `<id>` does not exist.
    - Body: `{"error": "Bookmark not found"}`
  - Status: `400 Bad Request`
    - Conditions:
      - Non-integer or non-positive `<id>` in URL path.
      - Malformed JSON body or empty payload.
      - No updatable fields provided in payload (payload contains no allowed keys).
      - `title` is provided but empty or whitespace-only.
      - `url` is provided but empty, whitespace-only, or invalid format.
      - `notes` is provided but is not a string.
      - `is_favorite` is provided but is not a boolean.
      - `archived` is provided but is not a boolean.
    - Body: `{"error": "Invalid update payload"}`

---

### 3.6 `DELETE /api/bookmarks/<id>`
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
    - Body: `{"error": "Bookmark not found"}`
  - Status: `400 Bad Request`
    - Condition: Non-integer or non-positive `<id>` in URL path.
    - Body: `{"error": "Invalid bookmark ID"}`

---

### 3.7 `POST /api/bookmarks/<id>/archive`
Convenience action endpoint to mark a bookmark as archived (`archived = true`).

- **Request**:
  - Method: `POST`
  - Path: `/api/bookmarks/<id>/archive`
- **Success Response**:
  - Status: `200 OK`
  - Body: Complete updated bookmark record with `"archived": true`.
- **Error Responses**:
  - Status: `404 Not Found` if bookmark doesn't exist.
  - Status: `400 Bad Request` if invalid bookmark ID.

---

### 3.8 `POST /api/bookmarks/<id>/restore`
Convenience action endpoint to restore an archived bookmark back to active (`archived = false`).

- **Request**:
  - Method: `POST`
  - Path: `/api/bookmarks/<id>/restore`
- **Success Response**:
  - Status: `200 OK`
  - Body: Complete updated bookmark record with `"archived": false`.
- **Error Responses**:
  - Status: `404 Not Found` if bookmark doesn't exist.
  - Status: `400 Bad Request` if invalid bookmark ID.

---

### 3.9 Search Filtering & Notes Query Semantics

The REST API supports comprehensive search filtering across bookmarks:

1. **Endpoint**: `GET /api/bookmarks?q=<term>`
2. **Target Fields**: The search term is matched against `title`, `url`, and `notes`. A bookmark is returned if the keyword appears as a substring in ANY of these three fields.
3. **Matching Behavior**:
   - Case-insensitive substring matching (`instr(LOWER(COALESCE(field, '')), LOWER(?)) > 0`).
   - Query string is trimmed of leading and trailing whitespace.
   - If `q` contains only whitespace or is empty (e.g., `?q=` or `?q=%20`), filtering is bypassed and all bookmarks are returned.
   - Supports search terms matching inside multiline notes, across punctuation, or within specific words.
4. **Combination with Favorites Filter**:
   - `GET /api/bookmarks?favorites=true&q=<term>` applies logical `AND`: the bookmark must match `q` in `title`, `url`, or `notes`, AND must have `is_favorite = 1`.

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
- `app/database.py`:
  - `init_db(db_path)`: Initializes SQLite schema with `notes TEXT DEFAULT ''` and `is_favorite INTEGER DEFAULT 0`, executing backward-compatible migrations if columns are missing.
  - `get_bookmarks(q=None, favorites_only=False, db_path=DEFAULT_DB_PATH)`: Queries bookmarks ordered by `id ASC`, applying substring search across `title`, `url`, and `notes`, and filtering by favorite status. Returns dictionaries with guaranteed string `notes`.
  - `get_bookmark_by_id(id, db_path=DEFAULT_DB_PATH)`: Fetches a single bookmark record by integer ID.
  - `create_bookmark(title, url, notes="", is_favorite=False, db_path=DEFAULT_DB_PATH)`: Inserts a new bookmark record with normalized `notes` (coalescing `None` to `""`).
  - `update_bookmark(id, title=None, url=None, notes=None, is_favorite=None, db_path=DEFAULT_DB_PATH)`: Updates specified fields, correctly applying new `notes` (including clearing notes when `notes=""` is passed), updating `updated_at`.
  - `delete_bookmark(id, db_path=DEFAULT_DB_PATH)`: Removes bookmark by ID.
- `app/server.py`:
  - Implements `MiniLinksHandler(http.server.BaseHTTPRequestHandler)` dispatching `GET`, `POST`, `PATCH`, `DELETE`, and `OPTIONS`.
  - Enforces schema validation on `notes` (ensuring it is a string if present).
  - Serializes responses to JSON with `Content-Type: application/json; charset=utf-8`.
  - Serves static assets from `web/` with strict directory traversal prevention.

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
- **Search Bar**: Input field (`id="search-input"`) with placeholder `"Search bookmarks by title, URL, or notes..."`. Debounced query filtering (250ms delay) triggers `GET /api/bookmarks?q=<term>` (preserving the active favorites filter state) and updates the displayed cards list.
- **Filter Bar & Favorites Toggle**:
  - Filter control bar containing the favorites filter toggle button (`id="filter-favorites-btn"`).
  - Toggles between showing all bookmarks and showing only favorited bookmarks.
  - When favorites filter is active, triggers `GET /api/bookmarks?favorites=true` (combining with `q` search term if present).
  - Provides visual active indicator (active CSS class, highlighted styling, and star icon state: `★ Favorites` active vs `☆ Favorites` inactive).
- **Bookmark Creation Form**:
  - Input for `title` (required text input, `id="bookmark-title"`).
  - Input for `url` (required URL/text input, `id="bookmark-url"`).
  - Textarea for `notes` (optional multiline text, `id="bookmark-notes"`):
    - Element: `<textarea id="bookmark-notes" name="notes" class="form-input form-textarea" rows="2" placeholder="Optional notes, tags, or description..."></textarea>`.
  - Submit button (`id="bookmark-submit-btn"`) to create the bookmark via `POST /api/bookmarks`.
- **Bookmarks List / Cards Grid**:
  - Container (`id="bookmarks-list"`) rendering responsive bookmark cards.
  - Displays an empty state message if no bookmarks exist or no bookmarks match the search/filter criteria.

### 6.2 Bookmark Card Elements & Interactions
Each bookmark card rendered must display:
- **Favorite / Star Toggle Button**: Star button (`id="favorite-btn-<id>"`, class `favorite-toggle-btn`) displaying a filled star `★` if favorited (`is_favorite: true`) or an outlined star `☆` if not favorited (`is_favorite: false`).
  - Clicking the star button dispatches `PATCH /api/bookmarks/<id>` with payload `{"is_favorite": !currentStatus}`.
  - On receiving `200 OK`, immediately updates the star icon (`★` $\leftrightarrow$ `☆`), updates the card's internal state, and if the favorites filter is currently active and the item was unfavorited, removes the card from view.
- **Title**: Formatted title displaying the bookmark name, linking directly to the URL (`target="_blank"`, `rel="noopener noreferrer"`).
- **URL**: Visible destination URL with clean truncation if long.
- **Notes**: Formatted notes block displaying bookmark notes if present (see Section 6.3).
- **Timestamps**: Display created timestamp (`Created: ...`) and updated timestamp (`Updated: ...` if mutated).
- **Action Controls**:
  - **Edit Button**: Opens the edit modal prefilled with the bookmark's title, URL, and notes, dispatching `PATCH /api/bookmarks/<id>` on submit.
  - **Delete Button**: Opens the confirmation modal, dispatching `DELETE /api/bookmarks/<id>` on confirmation with immediate removal from the DOM.
- **Error & Status Notifications**: Clear visual feedback (banner or toast) on network failures, validation errors, and successful operations.

### 6.3 Bookmark Notes Display & Editing Specification

The notes feature provides users with dedicated display and editing capabilities on every bookmark card:

#### 6.3.1 Creation Form Notes Interface
- The creation form provides a multiline `<textarea>` element with `id="bookmark-notes"`.
- Placeholder text: `"Optional notes, tags, or description..."`.
- Submitting the form reads the trimmed value: `const notes = bookmarkNotesInput.value.trim();`.
- Payload sent to `POST /api/bookmarks`: `{ title, url, notes }`.
- Upon successful creation, the form is reset, clearing the notes textarea alongside the title and URL inputs.

#### 6.3.2 Bookmark Card Notes Display
- **Conditional Rendering**: Notes are rendered inside the bookmark card if and only if the `notes` attribute contains non-empty text after trimming (`bookmark.notes && bookmark.notes.trim()`).
- **DOM Element Structure**:
  ```html
  <div class="card-notes">Official Python 3 library reference and tutorial</div>
  ```
- **Omission on Empty**: If a bookmark has no notes (i.e. `notes` is `""`), the `<div class="card-notes">` element is completely omitted from the card DOM, ensuring the card remains compact without extraneous whitespace or blank containers.
- **XSS Prevention**: Bookmark notes must be inserted into the DOM using safe text assignment (`notesBlock.textContent = bookmark.notes;`) or `document.createTextNode()`. Using `innerHTML` for notes rendering is strictly forbidden to prevent stored cross-site scripting (XSS) from arbitrary user content.
- **Typography & Formatting**:
  - `white-space: pre-wrap;`: Preserves user-entered line breaks, spacing, and formatting.
  - `word-break: break-word;`: Prevents lengthy unbroken strings (such as long URLs or code tokens inside notes) from overflowing the card boundary or breaking the CSS grid.
  - `background-color: var(--surface-alt);`: Subtle contrasting background distinguishing notes from the card surface.
  - `padding: 0.625rem 0.75rem;`: Ample internal spacing for readability.
  - `border-radius: var(--radius);`: Harmonious rounded corners matching the design system.
  - `flex-grow: 1;`: Ensures balanced card heights in responsive grid rows.

#### 6.3.3 Bookmark Notes Editing Interface
- **Modal Dialog**: Editing is conducted via the accessible modal dialog (`id="edit-modal"`).
- **Edit Notes Textarea**:
  - The modal form contains `<textarea id="edit-notes" name="notes" class="form-input form-textarea" rows="3" placeholder="Optional notes, tags, or description..."></textarea>`.
- **Prefilling**:
  - When the user clicks the "Edit" button on any bookmark card, `openEditModal(bookmark)` prefills `editNotesInput.value = bookmark.notes || '';` alongside `editTitleInput` and `editUrlInput`.
- **Saving Updates**:
  - Submitting the edit form reads `const notes = editNotesInput.value.trim();`.
  - Dispatches `PATCH /api/bookmarks/<id>` with payload `{ title, url, notes }`.
  - **Clearing Notes**: If the user erases all content from the notes textarea and clicks "Save Changes", an empty string `""` is sent as `notes`. The backend updates the database to `""`, and the re-rendered card automatically omits the `.card-notes` container.
  - **Modifying Notes**: Any changes or additions to notes are saved and immediately reflected on the card.
- **User Feedback & Focus Management**:
  - On save success, the modal closes, a success notification banner is displayed ("Bookmark updated successfully"), and the bookmark list is refreshed or updated in place.
  - On failure, an error banner is displayed and the modal remains open with user inputs intact.

#### 6.3.4 Search & Notes Filtering Interaction
- When a user enters text into the search bar (`#search-input`), the frontend sends `GET /api/bookmarks?q=<term>`.
- The backend matches `<term>` across bookmark notes in addition to titles and URLs.
- Matching bookmark cards display their notes, allowing users to find bookmarks by tags, keywords, or summary notes written months earlier.

### 6.4 Responsive Design & Visual Styling
- Mobile-first, responsive CSS (Flexbox / CSS Grid).
- Card grid adapts from single-column on mobile (`< 640px`) to multi-column (`repeat(auto-fill, minmax(320px, 1fr))`) on wider displays.
- `.form-textarea`: Styled with consistent border, background, focus ring (`box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15)`), and smooth resize behavior (`resize: vertical; min-height: 60px;`).

---

## 7. Testing Requirements & Test Harness

Testing is implemented strictly using Python's standard library `unittest`, `urllib.request`, `sqlite3`, and `threading`. Tests must not depend on any third-party packages.

### 7.1 Unit & Integration Test Suites in `tests/`

#### 7.1.1 `tests/test_api.py`
Validates all HTTP API endpoints against a live server running on an ephemeral port with an isolated temporary SQLite database:
1. Server bootstrap and `GET /health` responding with `200 OK` and `{"status": "ok"}`.
2. Initial bookmark listing `GET /api/bookmarks` returning an empty array `[]`.
3. Creating bookmarks via `POST /api/bookmarks` with valid payloads:
   - With explicit `notes` string, verifying `201 Created` and `notes` matching in response and SQLite table.
   - With omitted `notes` or `notes: null`, verifying default `notes: ""` in response and SQLite table.
   - With default `is_favorite: false` and explicit `is_favorite` boolean values.
4. Creating bookmarks with invalid payloads:
   - Missing title, empty url, non-string title/url verifying `400 Bad Request`.
   - Non-string `notes` (e.g. integer `{"notes": 999}`) verifying `400 Bad Request`.
   - Non-boolean `is_favorite` verifying `400 Bad Request`.
5. Search filtering via `GET /api/bookmarks?q=<searchterm>`:
   - Verifying matching against `notes` text (case-insensitive substring match).
   - Verifying matching against `title` and `url`.
   - Verifying empty results for non-matching queries, and full results for empty or whitespace query.
6. Retrieving single bookmark via `GET /api/bookmarks/<id>` returning complete object including `notes` string.
7. Updating bookmarks via `PATCH /api/bookmarks/<id>`:
   - Updating `notes` to a new string, verifying `200 OK` and updated `notes`.
   - Clearing `notes` by updating to `""`, verifying `notes` is cleared to empty string.
   - Rejecting non-string `notes` with `400 Bad Request`.
   - Updating `title`, `url`, and toggling `is_favorite`.
8. Favorite filtering via `GET /api/bookmarks?favorites=true` verifying only favorited bookmarks are returned, and combining `favorites=true` with search query `q` across notes.
9. Error responses: verifying `400 Bad Request` on malformed JSON, invalid payload, or non-boolean `is_favorite`, and `404 Not Found` for non-existent IDs on `PATCH` and `DELETE`.
10. Deleting bookmarks via `DELETE /api/bookmarks/<id>` verifying `200 OK` and subsequent 404 response on repeated deletion.
11. Static file delivery: verifying retrieval of `/`, `/index.html`, `/style.css`, and `/app.js` with correct MIME types.
12. Directory traversal protection: verifying requests with `../` or encoded traversal paths are rejected with `403` or `404`.

#### 7.1.2 `tests/test_persistence.py`
Validates SQLite persistence across server lifecycle restarts:
1. Starts Server 1 on an ephemeral port with a temporary `db_path`.
2. Inserts bookmarks into Server 1 via `POST /api/bookmarks` with varied notes content and favorite status.
3. Updates bookmark notes and toggles favorite status via `PATCH /api/bookmarks/<id>`.
4. Shuts down Server 1 cleanly (`server.shutdown()`, `server.server_close()`).
5. Verifies database file integrity directly using the `sqlite3` module, including `notes` stored as `TEXT` and `is_favorite` stored as `0` or `1`.
6. Starts Server 2 pointing to the same `db_path` on a new ephemeral port.
7. Verifies all previously created bookmarks, updated notes, favorite status, and timestamps persist and are queryable via `GET /api/bookmarks`.
8. Shuts down Server 2 and cleans up temporary database files.

---

### 7.2 Standalone 12-Step Smoke Test: `scripts/smoke_test.py`

`scripts/smoke_test.py` is a standalone executable Python script that executes an end-to-end verification scenario against an ephemeral server instance. It prints deterministic progress logs for each step and exits with status code `0` on total success or non-zero on any assertion failure.

#### The 12 Deterministic Steps:
1. **Step 1 - Server Bootstrap**: Start `create_server(host='127.0.0.1', port=0, db_path=temp_db)` on an ephemeral port; acquire bound port.
2. **Step 2 - Health Check**: Send `GET /health`; assert HTTP 200 and payload `{"status": "ok"}`.
3. **Step 3 - Initial Empty State**: Send `GET /api/bookmarks`; assert HTTP 200 and payload is an empty list `[]`.
4. **Step 4 - Create Bookmark (Valid)**: Send `POST /api/bookmarks` with `{"title": "Python Docs", "url": "https://docs.python.org", "notes": "Official Docs"}`; assert HTTP 201, `id` is positive integer, `notes` is `"Official Docs"`, `is_favorite` defaults to `False`, fields match, and timestamps are populated.
5. **Step 5 - Create Bookmark Validation Error**: Send `POST /api/bookmarks` with invalid payload `{"title": ""}`; assert HTTP 400.
6. **Step 6 - Verify Bookmark Listing**: Send `GET /api/bookmarks`; assert HTTP 200 and list contains exactly 1 bookmark matching Step 4 with `notes: "Official Docs"`.
7. **Step 7 - Search Filtering**: Send `GET /api/bookmarks?q=Python`; assert HTTP 200 with 1 result. Send `GET /api/bookmarks?q=Docs` (matching notes); assert HTTP 200 with 1 result. Send `GET /api/bookmarks?q=NonExistentTerm`; assert HTTP 200 with 0 results.
8. **Step 8 - Update Bookmark & Favorite**: Send `PATCH /api/bookmarks/<id>` with `{"notes": "Updated Documentation Notes", "is_favorite": true}`; assert HTTP 200, `notes` updated, `is_favorite` is `True`, `updated_at` updated. Also verify `GET /api/bookmarks?favorites=true` returns the bookmark.
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
│   ├── database.py            # SQLite schema initialization, notes handling, and query operations
│   └── server.py              # HTTP request handler, routing, notes validation, and create_server factory
├── web/
│   ├── index.html             # Responsive bookmark manager HTML interface with notes inputs
│   ├── style.css              # Modern responsive CSS styling including card-notes and textarea styles
│   └── app.js                 # Vanilla JavaScript API client, card notes rendering, and modal notes editor
├── tests/
│   ├── __init__.py            # Test package marker
│   ├── test_api.py            # unittest suite for REST API endpoints, notes CRUD/search, & static files
│   └── test_persistence.py    # unittest suite for database restart persistence including notes
└── scripts/
    └── smoke_test.py          # Standalone 12-step deterministic smoke verification
```

---

## 9. Deterministic Quality Gates & Verification Matrix

Before code is accepted or merged, the following automated checks must pass:
1. **Compilation Check**: `python3 -m compileall app tests scripts` passes with zero syntax errors.
2. **Unit Test Suite**: `python3 -m unittest discover -s tests -p "test_*.py"` completes with 100% passing tests.
3. **Smoke Test Execution**: `python3 scripts/smoke_test.py` completes all 12 steps and exits with status 0.
