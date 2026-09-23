# MiniLinks Product Specification

## 1. Executive Summary & Overview

**MiniLinks** is a zero-dependency, lightweight, single-user bookmark manager web application designed for local operation. It provides an intuitive, responsive web interface for saving, organizing, favoriting, searching, editing, soft-archiving, restoring, and deleting bookmarks with associated notes, tags, and URLs. The application is backed by a robust, standard-library-only Python HTTP server and SQLite database storage.

### Core Architectural Principles
- **Zero Third-Party Dependencies**: Built strictly using the Python 3 standard library (`http.server`, `sqlite3`, `json`, `urllib`, `unittest`, `threading`, `pathlib`, `os`) and standard web technologies (vanilla HTML5, CSS3, and modern ES6+ JavaScript).
- **Process & Test Isolation**: Headless server instantiation with configurable host, ephemeral port binding (`port=0`), and isolated database paths to enable concurrent execution and automated testing without port collisions or file locks.
- **Contract Determinism**: Explicit REST API endpoints, strict schema validation, predictable HTTP status codes, and unambiguous data contracts.
- **Persistence Integrity**: Atomic, ACID-compliant persistence using SQLite with transactional operations and integrity constraints.
- **Directory Traversal Security**: Strict path sanitization for static file serving, preventing unauthorized access outside the designated web directory.

### Key Feature Set
- **Bookmark Management**: Create, view, edit, and delete web bookmarks with validated titles and URLs.
- **Optional Bookmark Notes**: Attach optional multiline notes, descriptions, or annotations to bookmarks, persisted in SQLite and fully manageable via REST API and frontend UI.
- **Categorical Tags**: Assign lightweight categorical tags stored as JSON arrays and queryable via dedicated tag filtering endpoints.
- **Favorite / Star Pinning**: Fast toggle mechanism to favorite bookmarks and filter the dashboard to display only favorited items.
- **Bookmark Archiving & Restoration**: Soft-archive bookmarks to declutter the main view without permanent deletion. Includes dedicated archive and restore action endpoints, visual indicators on cards (status badges and container styling), and flexible query filter views (active by default, archived only, or all bookmarks).
- **Full-Text Substring Search**: Real-time debounced search filtering bookmarks across title, URL, and notes text simultaneously.
- **Modal Editing**: In-place editing modal enabling seamless updates to title, destination URL, notes, and tags with instant DOM synchronization.

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
- `archived`: Stored as SQLite `INTEGER` (`0` for `false` / active, `1` for `true` / archived) with default `0`. In JSON API request and response payloads, it is represented and serialized as a native boolean (`true` or `false`). Non-boolean values in API payloads (such as strings `"true"`/`"false"`, numbers `1`/`0`, arrays, objects, or `null`) must be rejected with `400 Bad Request`.
- `created_at`: Set automatically at insert time in ISO 8601 UTC format (`YYYY-MM-DDTHH:MM:SSZ`); never mutated on updates.
- `updated_at`: Set automatically at insert time; updated to the current ISO 8601 UTC timestamp on every modification (`PATCH`, archive, restore).

### 2.4 Timestamp Standards
- Timestamps must follow ISO-8601 format in UTC: `YYYY-MM-DDTHH:MM:SSZ` generated via Python `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.

### 2.5 Optional Bookmark Notes Attribute Specification (`notes`)

The `notes` attribute provides user-authored context, annotations, or detailed descriptions for a bookmark:

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
   - If provided as a string: preserved exactly as supplied.
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

### 2.7 Bookmark Archived Attribute Specification (`archived`)

The `archived` attribute provides soft-archival capabilities for bookmarks, allowing users to remove clutter from the main view while preserving bookmark data for future retrieval:

1. **Storage Representation**:
   - Column definition: `archived INTEGER DEFAULT 0`.
   - Stored in SQLite as `INTEGER DEFAULT 0`, where `0` represents an active (unarchived) bookmark and `1` represents an archived bookmark.
   - Backward compatibility migration: older databases created before the introduction of the `archived` column are automatically migrated during database initialization (`init_db`) via:
     ```sql
     ALTER TABLE bookmarks ADD COLUMN archived INTEGER DEFAULT 0;
     UPDATE bookmarks SET archived = 0 WHERE archived IS NULL;
     ```
2. **Payload Serialization**:
   - Every bookmark object returned in JSON API responses contains the key `"archived"` mapped strictly to a native JSON boolean value:
     - Active bookmark: `"archived": false`
     - Archived bookmark: `"archived": true`
   - It is never returned as an integer (`0` or `1`), never returned as a string (`"false"` or `"true"`), never returned as `null`, and never omitted from bookmark representations.
3. **Creation Semantics**:
   - In `POST /api/bookmarks`, `archived` is entirely optional.
   - If omitted from the request payload: defaults to `false` (`archived = 0` in SQLite).
   - If explicitly provided as `false`: saved as `0` in SQLite.
   - If explicitly provided as `true`: saved as `1` in SQLite, creating the bookmark directly in archived status.
   - If provided as any non-boolean type (e.g., string `"true"`, string `"false"`, number `1`, number `0`, array, object, or `null` when a value is expected): rejected with `400 Bad Request` (`{"error": "archived must be a boolean if provided"}`).
4. **Update Semantics**:
   - In `PATCH /api/bookmarks/<id>`, `archived` can be updated directly via boolean payload (e.g., `{"archived": true}` or `{"archived": false}`).
   - Dedicated action endpoints `POST /api/bookmarks/<id>/archive` and `POST /api/bookmarks/<id>/restore` provide convenient action triggers without requiring a request body.
   - Mutating the archive state updates the bookmark's `updated_at` ISO 8601 timestamp.
   - Non-boolean values supplied in `PATCH` are rejected with `400 Bad Request` (`{"error": "Invalid update payload"}`).
5. **Archive Filtering & Default Visibility**:
   - **Default Behavior (`GET /api/bookmarks`)**: Returns only active, unarchived bookmarks (`COALESCE(archived, 0) = 0`). Archived bookmarks are hidden by default to keep the user's working collection clean.
   - **Explicit Active Filter (`GET /api/bookmarks?archived=false`)**: Identical to the default behavior; returns only active, non-archived bookmarks (`COALESCE(archived, 0) = 0`).
   - **Archived-Only Filter (`GET /api/bookmarks?archived=true`)**: Returns exclusively archived bookmarks (`COALESCE(archived, 0) = 1`).
   - **All Bookmarks Filter (`GET /api/bookmarks?archived=all`)**: Bypasses archive filtering and returns all bookmarks regardless of archive status (`archived = 0` and `archived = 1`).
   - Archive filtering operates in logical conjunction (`AND`) with search filtering (`q`), favorites filtering (`favorites`), and tag filtering (`tag`).

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
Retrieves a list of bookmarks, with optional query parameter filtering by search term (`q`), favorite status (`favorites`), categorical tag (`tag`), and archive status (`archived`).

- **Request**:
  - Method: `GET`
  - Path: `/api/bookmarks`
  - Optional Query Parameters:
    - `q` (optional, `string`): Search keyword. When provided and non-empty, filters bookmarks where `title`, `url`, `notes`, or `tags` contains the search term (case-insensitive substring match). When omitted or empty/whitespace-only, search filtering is not applied.
    - `favorites` (optional, `string`): Favorite filter flag. When set to `'true'` (case-insensitive, e.g. `?favorites=true`), returns only bookmarks marked as favorite (`is_favorite = 1`). When omitted, empty, or `'false'`, favorite filtering is not applied.
    - `tag` (optional, `string`): Tag filter. When provided, filters bookmarks whose `tags` list contains the specified tag (case-insensitive match).
    - `archived` (optional, `string`): Archive filter flag.
      - When omitted, empty, or `'false'`, returns only active, unarchived bookmarks (`archived = 0`). This is the default behavior.
      - When set to `'true'` (or `'1'`), returns only archived bookmarks (`archived = 1`).
      - When set to `'all'` (or `'*'`), returns all bookmarks regardless of archive status (`archived = 0` and `archived = 1`).
- **Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: JSON array of bookmark objects ordered by `id ASC`. Every bookmark object includes `notes` (string, `""` when empty), `tags` (array of strings, `[]` when empty), `is_favorite` (native boolean), and `archived` (native boolean). Returns an empty array `[]` if no bookmarks match.
    ```json
    [
      {
        "id": 1,
        "title": "Python Documentation",
        "url": "https://docs.python.org/3/",
        "notes": "Official Python 3 library reference and tutorial",
        "tags": ["python", "docs"],
        "is_favorite": true,
        "archived": false,
        "created_at": "2026-09-23T00:00:00Z",
        "updated_at": "2026-09-23T00:00:00Z"
      },
      {
        "id": 2,
        "title": "SQLite Tutorial",
        "url": "https://www.sqlite.org/",
        "notes": "",
        "tags": ["database"],
        "is_favorite": false,
        "archived": false,
        "created_at": "2026-09-23T00:01:00Z",
        "updated_at": "2026-09-23T00:05:00Z"
      }
    ]
    ```

---

### 3.3 `GET /api/bookmarks/<id>`
Retrieves a single bookmark by its unique integer ID.

- **Request**:
  - Method: `GET`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete bookmark object including `notes`, `tags`, `is_favorite`, and `archived`.
    ```json
    {
      "id": 1,
      "title": "Python Documentation",
      "url": "https://docs.python.org/3/",
      "notes": "Official Python 3 library reference and tutorial",
      "tags": ["python", "docs"],
      "is_favorite": true,
      "archived": false,
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
      "tags": ["web", "standards"],
      "is_favorite": false,
      "archived": false
    }
    ```
    - `title` (required, `string`): Non-empty string after trimming whitespace.
    - `url` (required, `string`): Non-empty URL string starting with `http://` or `https://` with valid hostname.
    - `notes` (optional, `string`): Optional user notes or annotations. If omitted or passed as `null`, defaults to `""`. Non-string types rejected with `400 Bad Request`.
    - `tags` (optional, `array` of `string`): Optional list of tag strings. If omitted or `null`, defaults to `[]`. Non-array types or arrays containing non-strings rejected with `400 Bad Request`.
    - `is_favorite` (optional, `boolean`): Optional favorite flag (defaults to `false` if omitted). Non-boolean types rejected with `400 Bad Request`.
    - `archived` (optional, `boolean`): Optional archive flag (defaults to `false` if omitted). When supplied, must be a native boolean (`true` or `false`). Non-boolean types rejected with `400 Bad Request`.
- **Success Response**:
  - Status: `201 Created`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete bookmark object including generated `id`, `created_at`, `updated_at`, `notes`, `tags`, `is_favorite`, and `archived`.
    ```json
    {
      "id": 3,
      "title": "MDN Web Docs",
      "url": "https://developer.mozilla.org/",
      "notes": "Web standards, HTML, CSS, and JavaScript guides",
      "tags": ["web", "standards"],
      "is_favorite": false,
      "archived": false,
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:10:00Z"
    }
    ```
- **Error Responses**:
  - Status: `400 Bad Request`
    - Conditions:
      - Missing request body or empty payload.
      - Malformed JSON syntax.
      - JSON body is not a JSON object.
      - Missing, empty, or whitespace-only `title` or `url`.
      - Invalid URL format (missing scheme `http://`/`https://` or host).
      - `notes` is provided but is not a string (e.g. `{"notes": 123}`).
      - `tags` is provided but is not an array of strings.
      - `is_favorite` is provided but is not a boolean (e.g. `{"is_favorite": "true"}`).
      - `archived` is provided but is not a boolean (e.g. `{"archived": "false"}`, `{"archived": 1}`, or `{"archived": null}`).
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
      ```json
      {
        "error": "archived must be a boolean if provided"
      }
      ```

---

### 3.5 `PATCH /api/bookmarks/<id>`
Partially updates an existing bookmark's `title`, `url`, `notes`, `tags`, `is_favorite`, `archived`, or any combination thereof.

- **Request**:
  - Method: `PATCH`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
  - Headers: `Content-Type: application/json`
  - Body: JSON object containing one or more allowed fields to update:
    ```json
    {
      "archived": true
    }
    ```
    or
    ```json
    {
      "title": "MDN Web Docs - Updated",
      "notes": "Updated documentation notes",
      "is_favorite": true,
      "archived": false
    }
    ```
    - Updatable fields:
      - `title` (`string`, optional): Non-empty string after stripping whitespace.
      - `url` (`string`, optional): Non-empty valid URL string starting with `http://` or `https://`.
      - `notes` (`string`, optional): Updated notes text string. Supplying `""` clears existing notes. Must be a string if provided; non-string types rejected with `400 Bad Request`.
      - `tags` (`array` of `string`, optional): Updated tags list. Supplying `[]` clears existing tags. Must be an array of strings if provided; non-array or non-string elements rejected with `400 Bad Request`.
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
      "tags": ["web", "standards"],
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
      - `tags` is provided but is not an array of strings.
      - `is_favorite` is provided but is not a boolean.
      - `archived` is provided but is not a boolean.
    - Body: `{"error": "Invalid update payload"}`

---

### 3.6 `DELETE /api/bookmarks/<id>`
Deletes a bookmark permanently by ID.

- **Request**:
  - Method: `DELETE`
  - Path: `/api/bookmarks/<id>` where `<id>` is a positive integer.
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
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
Dedicated convenience action endpoint to mark a bookmark as archived (`archived = true`).

- **Request**:
  - Method: `POST`
  - Path: `/api/bookmarks/<id>/archive` where `<id>` is a positive integer.
  - Headers: None required (request body is ignored).
- **Semantics**:
  - Sets `archived` to `1` in SQLite.
  - Updates `updated_at` to the current UTC ISO 8601 timestamp.
  - Idempotent: if the bookmark is already archived, returns `200 OK` with the current record.
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete updated bookmark record with `"archived": true`.
    ```json
    {
      "id": 1,
      "title": "Python Documentation",
      "url": "https://docs.python.org/3/",
      "notes": "Official Python 3 library reference and tutorial",
      "tags": ["python", "docs"],
      "is_favorite": true,
      "archived": true,
      "created_at": "2026-09-23T00:00:00Z",
      "updated_at": "2026-09-23T00:20:00Z"
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

### 3.8 `POST /api/bookmarks/<id>/restore`
Dedicated convenience action endpoint to restore an archived bookmark back to active status (`archived = false`).

- **Request**:
  - Method: `POST`
  - Path: `/api/bookmarks/<id>/restore` where `<id>` is a positive integer.
  - Headers: None required (request body is ignored).
- **Semantics**:
  - Sets `archived` to `0` in SQLite.
  - Updates `updated_at` to the current UTC ISO 8601 timestamp.
  - Idempotent: if the bookmark is already active (unarchived), returns `200 OK` with the current record.
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body: Complete updated bookmark record with `"archived": false`.
    ```json
    {
      "id": 1,
      "title": "Python Documentation",
      "url": "https://docs.python.org/3/",
      "notes": "Official Python 3 library reference and tutorial",
      "tags": ["python", "docs"],
      "is_favorite": true,
      "archived": false,
      "created_at": "2026-09-23T00:00:00Z",
      "updated_at": "2026-09-23T00:25:00Z"
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

### 3.9 `GET /api/tags`
Retrieves a sorted list of all unique tags used across all bookmarks.

- **Request**:
  - Method: `GET`
  - Path: `/api/tags`
- **Success Response**:
  - Status: `200 OK`
  - Headers: `Content-Type: application/json; charset=utf-8`
  - Body:
    ```json
    {
      "tags": ["database", "docs", "python", "standards", "web"]
    }
    ```

---

### 3.10 Query Filtering & Parameter Combinations

The REST API supports combining query parameters on `GET /api/bookmarks`:

1. **Filtering Parameters**:
   - `q=<searchterm>`: Case-insensitive substring matching against `title`, `url`, `notes`, and `tags`.
   - `favorites=true`: Restricts results to bookmarks where `is_favorite = 1`.
   - `tag=<tag>`: Restricts results to bookmarks containing `<tag>` in their `tags` array.
   - `archived=<value>`:
     - Omitted, empty, or `false`: Restricts results to `archived = 0` (active unarchived bookmarks only).
     - `true` (or `1`): Restricts results to `archived = 1` (archived bookmarks only).
     - `all` (or `*`): Removes archive filtering; returns both active and archived bookmarks.
2. **Logical Conjunction**:
   - All active filter criteria are combined using logical `AND`.
   - Example: `GET /api/bookmarks?archived=true&favorites=true&q=python` returns bookmarks that are archived (`archived = 1`) **AND** favorited (`is_favorite = 1`) **AND** contain `"python"` in title, url, notes, or tags.
   - Example: `GET /api/bookmarks?archived=all&tag=dev` returns all bookmarks (both active and archived) tagged with `"dev"`.

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
  - `init_db(db_path)`: Initializes SQLite schema with `notes TEXT DEFAULT ''`, `tags TEXT DEFAULT '[]'`, `is_favorite INTEGER DEFAULT 0`, and `archived INTEGER DEFAULT 0`, executing backward-compatible migrations via `ALTER TABLE` if any columns are missing.
  - `get_bookmarks(q=None, favorites_only=False, tag=None, db_path=DEFAULT_DB_PATH, *, filter_tag=None, archived=False)`: Queries bookmarks ordered by `id ASC`, applying substring search across `title`, `url`, `notes`, and `tags`, filtering by favorite status, tag, and archive status (`False` for unarchived, `True` for archived, `'all'` for both). Returns dictionaries with native Python booleans for `is_favorite` and `archived`.
  - `get_bookmark_by_id(id, db_path=DEFAULT_DB_PATH)`: Fetches a single bookmark record by integer ID.
  - `create_bookmark(title, url, notes="", is_favorite=False, tags=None, db_path=DEFAULT_DB_PATH, *, archived=False)`: Inserts a new bookmark record with normalized `notes`, `tags`, `is_favorite`, and `archived` values.
  - `update_bookmark(id, title=None, url=None, notes=None, is_favorite=None, tags=None, db_path=DEFAULT_DB_PATH, *, archived=None)`: Updates specified fields, correctly applying new values and updating `updated_at`.
  - `archive_bookmark(id, db_path=DEFAULT_DB_PATH)`: Sets `archived = 1` and updates `updated_at`.
  - `restore_bookmark(id, db_path=DEFAULT_DB_PATH)`: Sets `archived = 0` and updates `updated_at`.
  - `delete_bookmark(id, db_path=DEFAULT_DB_PATH)`: Removes bookmark by ID.
  - `get_all_tags(db_path=DEFAULT_DB_PATH)`: Extracts distinct tags across all bookmarks sorted alphabetically.
- `app/server.py`:
  - Implements `MiniLinksHandler(http.server.BaseHTTPRequestHandler)` dispatching `GET`, `POST`, `PATCH`, `PUT`, `DELETE`, and `OPTIONS`.
  - Dispatches `POST /api/bookmarks/<id>/archive` and `POST /api/bookmarks/<id>/restore`.
  - Enforces schema validation on `notes`, `tags`, `is_favorite`, and `archived`.
  - Serializes responses to JSON with `Content-Type: application/json; charset=utf-8`.
  - Serves static assets from `web/` with strict directory traversal prevention.

### 5.2 Server Factory Interface: `create_server`

```python
def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    db_path: str = "minilinks.db",
    web_dir: Optional[Union[str, Path]] = None,
) -> MiniLinksServer:
    """
    Initializes the SQLite database at `db_path`, instantiates an HTTPServer
    bound to (host, port), and starts listening inside a background daemon thread.

    Parameters:
        host (str): Hostname or IP to bind (default: '127.0.0.1').
        port (int): Port number (default: 0 for OS-assigned ephemeral port).
        db_path (str | Path): File system path to the SQLite database.
        web_dir (str | Path, optional): Custom path to static web assets.

    Returns:
        MiniLinksServer:
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
- **Search Bar**: Input field (`id="search-input"`) with placeholder `"Search bookmarks by title, URL, or notes..."`. Debounced query filtering (250ms delay) triggers `GET /api/bookmarks?q=<term>` (preserving the active favorites and archive filter states) and updates the displayed cards list.
- **Filter Bar Controls**:
  - Filter control bar containing the favorites toggle button (`id="filter-favorites-btn"`) and archive toggle button (`id="filter-archived-btn"`).
  - **Favorites Toggle Button**:
    - Toggles between showing all active bookmarks and showing only favorited bookmarks.
    - Sets `aria-pressed` attribute and displays star state (`★ Favorites` active vs `☆ Favorites` inactive).
  - **Archived Toggle Button**:
    - Button with `id="filter-archived-btn"` and class `filter-archived-btn`.
    - Toggles between viewing active bookmarks (default) and viewing archived bookmarks (`?archived=true`).
    - When active, applies `.active` CSS class, sets `aria-pressed="true"`, and displays the archive icon `📦 Archived`.
- **Bookmark Creation Form**:
  - Input for `title` (required text input, `id="bookmark-title"`).
  - Input for `url` (required URL/text input, `id="bookmark-url"`).
  - Textarea for `notes` (optional multiline text, `id="bookmark-notes"`).
  - Input for `tags` (optional comma-separated text, `id="bookmark-tags"`).
  - Submit button (`id="bookmark-submit-btn"`) to create the bookmark via `POST /api/bookmarks`.
- **Bookmarks List / Cards Grid**:
  - Container (`id="bookmarks-list"`) rendering responsive bookmark cards in a responsive CSS Grid.
  - Displays descriptive empty state messages when no bookmarks exist or none match the active search/filter criteria.

### 6.2 Bookmark Card Elements & Interactions
Each bookmark card rendered must display:
- **Card Container**: Container element `.bookmark-card`. When the bookmark is archived (`archived: true`), the container carries the modifier class `.is-archived` (`class="bookmark-card is-archived"`).
- **Archived Status Badge**: For archived bookmarks, a distinct visual pill/badge `<span class="badge badge-archived">Archived</span>` is displayed in the card header next to the title or metadata, immediately identifying archived records.
- **Favorite / Star Toggle Button**: Star button (`id="favorite-btn-<id>"`, class `favorite-toggle-btn`) displaying a filled star `★` if favorited (`is_favorite: true`) or an outlined star `☆` if not favorited (`is_favorite: false`).
  - Clicking dispatches `PATCH /api/bookmarks/<id>` with payload `{"is_favorite": !currentStatus}`.
  - On `200 OK`, immediately updates the star icon (`★` $\leftrightarrow$ `☆`), updates internal state, and removes the card if the favorites filter is active and the item was unfavorited.
- **Title**: Formatted title displaying the bookmark name, linking directly to the URL (`target="_blank"`, `rel="noopener noreferrer"`).
- **URL**: Visible destination URL with clean truncation if long.
- **Notes**: Formatted notes block displaying bookmark notes if present.
- **Tags**: Formatted tag chips displaying bookmark tags if present. Clicking any tag chip filters the view by that tag.
- **Timestamps**: Display created timestamp (`Created: ...`) and updated timestamp (`Updated: ...` if mutated).
- **Action Controls**:
  - **Edit Button**: Opens the edit modal prefilled with the bookmark's title, URL, notes, and tags, dispatching `PATCH /api/bookmarks/<id>` on submit.
  - **Archive / Restore Button**:
    - Element: `<button type="button" class="btn btn-secondary btn-sm btn-archive ...">`.
    - When bookmark is active (`archived: false`): displays `📦 Archive` with title `"Archive bookmark"`. Clicking calls `POST /api/bookmarks/<id>/archive`.
    - When bookmark is archived (`archived: true`): displays `📤 Restore` with modifier class `.is-archived` (`btn-archive is-archived`) and title `"Restore bookmark"`. Clicking calls `POST /api/bookmarks/<id>/restore`.
    - On success, displays a toast notification ("Bookmark moved to archive" or "Bookmark restored from archive") and refreshes the bookmark list to synchronize state.
  - **Delete Button**: Opens the confirmation modal, dispatching `DELETE /api/bookmarks/<id>` on confirmation with immediate removal from the DOM.
- **Visual Indicators for Archived Status**:
  - Card container receives `.is-archived` class, visually differentiating archived bookmarks through muted background tones, dashed border accents, and subtle opacity styling.
  - Card displays the distinct `.is-archived` button state with `📤 Restore` label and icon.
  - Card displays the `.badge-archived` status badge.
  - In views displaying archived items (such as `?archived=true` or combined views `?archived=all`), visual cues immediately differentiate archived bookmarks from active bookmarks.

### 6.3 Bookmark Notes Display & Editing Specification

1. **Creation Form Notes Interface**:
   - The creation form provides a multiline `<textarea>` element with `id="bookmark-notes"`.
   - Placeholder text: `"Optional notes, annotations, or description..."`.
   - Submitting the form reads the trimmed value: `const notes = bookmarkNotesInput.value.trim();`.
   - Payload sent to `POST /api/bookmarks`: `{ title, url, notes, tags }`.
2. **Bookmark Card Notes Display**:
   - **Conditional Rendering**: Notes are rendered inside the bookmark card if and only if the `notes` attribute contains non-empty text after trimming (`bookmark.notes && bookmark.notes.trim()`).
   - **DOM Structure**: Safe text assignment into `<div class="card-notes"></div>` using `.textContent` to prevent XSS.
   - **Omission on Empty**: If a bookmark has no notes (`notes === ""`), the `.card-notes` element is completely omitted from the card DOM.
   - **Styling**: `white-space: pre-wrap; word-break: break-word; background-color: var(--surface-alt); padding: 0.625rem 0.75rem; border-radius: var(--radius);`.
3. **Bookmark Notes Editing Interface**:
   - The edit modal contains `<textarea id="edit-notes" name="notes" class="form-input form-textarea" rows="3"></textarea>`.
   - Prefilled with `bookmark.notes || ''` on edit modal open.
   - Submitting dispatches `PATCH /api/bookmarks/<id>` with payload `{ title, url, notes, tags }`.
   - Supplying an empty string clears notes.

### 6.4 Responsive Design & Visual Styling
- Mobile-first, responsive CSS (Flexbox / CSS Grid).
- Card grid adapts from single-column on mobile (`< 640px`) to multi-column (`repeat(auto-fill, minmax(320px, 1fr))`) on wider displays.
- `.form-textarea`: Styled with consistent border, background, focus ring, and vertical resize.

### 6.5 Bookmark Archiving UI & Interaction Specification

The archive feature allows users to declutter their active bookmarks collection without permanently losing saved links:

#### 6.5.1 Filter Bar Archive Controls & Toggle Interface
- **Filter Button Element**:
  ```html
  <button
    type="button"
    id="filter-archived-btn"
    class="filter-archived-btn"
    aria-pressed="false"
    title="Show archived bookmarks"
  >
    <span class="filter-archive-icon" aria-hidden="true">📦</span>
    <span class="filter-btn-label">Archived</span>
  </button>
  ```
- **Toggle Behavior & State Management**:
  - The UI tracks archive filter state via `isArchivedFilterActive` (boolean).
  - Clicking `#filter-archived-btn` toggles `isArchivedFilterActive = !isArchivedFilterActive`.
  - When `isArchivedFilterActive` is `true`:
    - The button receives the `.active` CSS class and `aria-pressed="true"`.
    - Styling transitions to an active indigo highlight (`background-color: #e0e7ff; color: #3730a3; border-color: #a5b4fc;`).
    - Dispatches `GET /api/bookmarks?archived=true`, preserving active `q` (search term) and `favorites` parameters if set.
    - The card grid updates to display exclusively archived bookmarks.
  - When `isArchivedFilterActive` is `false`:
    - The `.active` CSS class is removed and `aria-pressed="false"`.
    - Dispatches default `GET /api/bookmarks` (which returns only active, unarchived bookmarks with `archived = 0`).
    - The card grid returns to displaying active bookmarks.
- **Support for Multi-View Query Filtering**:
  - In addition to binary toggling, the REST API contract supports `?archived=all` (returning both active and archived bookmarks simultaneously).
  - When all bookmarks are returned in a combined view, archived bookmarks are immediately distinguished from active bookmarks via visual card cues (archived badge, container styling, and restore button).
- **Result Count Indicator**:
  - The counter `#bookmarks-count` dynamically updates to indicate both the count and the context of the displayed items:
    - Active view: `"X bookmarks"` (or `"X favorites"` if favorites filter is active).
    - Archived view: `"X archived bookmarks"`.

#### 6.5.2 Bookmark Card Archive / Restore Button
- **Button Construction**:
  Each rendered bookmark card includes a dedicated archive action button in its footer (`.card-footer`):
  ```javascript
  const isArchived = Boolean(bookmark.archived);
  const archiveBtn = document.createElement('button');
  archiveBtn.type = 'button';
  archiveBtn.className = `btn btn-secondary btn-sm btn-archive${isArchived ? ' is-archived' : ''}`;
  archiveBtn.innerHTML = `
    <span class="btn-archive-icon" aria-hidden="true">${isArchived ? '📤' : '📦'}</span>
    ${isArchived ? 'Restore' : 'Archive'}
  `;
  archiveBtn.title = isArchived ? 'Restore bookmark' : 'Archive bookmark';
  ```
- **Action Execution & API Dispatch**:
  - Clicking the button invokes `handleToggleArchive(bookmark.id, isArchived)`.
  - If the bookmark is currently active (`isArchived === false`):
    - Dispatches `POST /api/bookmarks/<id>/archive`.
    - On HTTP 200 response: displays a success toast notification `"Bookmark moved to archive"`.
  - If the bookmark is currently archived (`isArchived === true`):
    - Dispatches `POST /api/bookmarks/<id>/restore`.
    - On HTTP 200 response: displays a success toast notification `"Bookmark restored from archive"`.
  - On error: displays an error toast notification with the server error message.
  - On completion: automatically synchronizes the bookmarks list via `fetchBookmarks(...)` so cards seamlessly appear or disappear in accordance with the active filter mode.

#### 6.5.3 Card Visual Indicators & Styling
- **Action State Label & Icon**:
  - Active bookmark: displays package icon `📦` with label `"Archive"` and title `"Archive bookmark"`.
  - Archived bookmark: displays outbox icon `📤` with label `"Restore"` and title `"Restore bookmark"`.
- **Button Modifier Class**:
  - Archived bookmark buttons carry the `.is-archived` modifier class (`.btn-archive.is-archived`), providing immediate visual distinction.
- **Card Container Styling & Status Badge**:
  - In views displaying archived items (such as `?archived=true` or `?archived=all`), cards with `archived: true` exhibit distinct visual indicators:
    - The card element receives the `.is-archived` class (`.bookmark-card.is-archived`), rendering with a subtle dashed border and softened background.
    - An archived status badge `<span class="badge badge-archived">Archived</span>` is displayed in the card header next to the title or metadata tags.
    - Visual differentiation via `.is-archived` styling on the action button (`📤 Restore`).
    - Clear visual cues preventing accidental interaction with unarchived collections.
- **Empty States for Archived View**:
  - When the archived filter is active and no archived bookmarks exist, the UI renders a dedicated empty state:
    - Icon: `📦`
    - Title: `"No archived bookmarks"`
    - Subtitle: `"Bookmarks you archive will appear here. Archive bookmarks you don't need right now to keep your collection clean."`

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
   - With default `archived: false` and explicit `archived: true` / `false` boolean values.
4. Creating bookmarks with invalid payloads:
   - Missing title, empty url, non-string title/url verifying `400 Bad Request`.
   - Non-string `notes` (e.g. integer `{"notes": 999}`) verifying `400 Bad Request`.
   - Non-boolean `is_favorite` verifying `400 Bad Request`.
   - Non-boolean `archived` (e.g. `{"archived": "true"}` or `{"archived": 1}`) verifying `400 Bad Request`.
5. Search filtering via `GET /api/bookmarks?q=<searchterm>`:
   - Verifying matching against `notes` text (case-insensitive substring match).
   - Verifying matching against `title` and `url`.
   - Verifying empty results for non-matching queries, and full results for empty or whitespace query.
6. Tag filtering via `GET /api/bookmarks?tag=<tag>` and tag index `GET /api/tags`.
7. Retrieving single bookmark via `GET /api/bookmarks/<id>` returning complete object including `notes`, `tags`, `is_favorite`, and `archived`.
8. Updating bookmarks via `PATCH /api/bookmarks/<id>`:
   - Updating `notes` to a new string, verifying `200 OK` and updated `notes`.
   - Clearing `notes` by updating to `""`, verifying `notes` is cleared to empty string.
   - Updating `tags`, `title`, `url`, and toggling `is_favorite`.
   - Updating `archived` via boolean payload, rejecting non-boolean `archived` with `400 Bad Request`.
9. Archive and Restore Endpoints:
   - `POST /api/bookmarks/<id>/archive` marks bookmark as archived (`archived = true`), updates `updated_at`, returns `200 OK`.
   - `POST /api/bookmarks/<id>/restore` restores bookmark to active (`archived = false`), updates `updated_at`, returns `200 OK`.
   - Non-existent bookmark ID returns `404 Not Found`.
   - Invalid bookmark ID returns `400 Bad Request`.
10. Archive Query Filtering:
    - Default `GET /api/bookmarks` returns only active bookmarks (`archived = 0`).
    - Explicit `GET /api/bookmarks?archived=false` returns only active bookmarks.
    - Explicit `GET /api/bookmarks?archived=true` returns only archived bookmarks (`archived = 1`).
    - Explicit `GET /api/bookmarks?archived=all` returns both active and archived bookmarks.
11. Favorite filtering via `GET /api/bookmarks?favorites=true` verifying only favorited bookmarks are returned, and combining `favorites=true` with search query `q` and archive filters.
12. Error responses: verifying `400 Bad Request` on malformed JSON, invalid payload, or non-boolean flags, and `404 Not Found` for non-existent IDs on `PATCH`, `DELETE`, and archive/restore endpoints.
13. Deleting bookmarks via `DELETE /api/bookmarks/<id>` verifying `200 OK` and subsequent 404 response on repeated deletion.
14. Static file delivery: verifying retrieval of `/`, `/index.html`, `/style.css`, and `/app.js` with correct MIME types.
15. Directory traversal protection: verifying requests with `../` or encoded traversal paths are rejected with `403` or `404`.

#### 7.1.2 `tests/test_persistence.py`
Validates SQLite persistence across server lifecycle restarts:
1. Starts Server 1 on an ephemeral port with a temporary `db_path`.
2. Inserts bookmarks into Server 1 via `POST /api/bookmarks` with varied notes content, tags, favorite status, and archive status.
3. Updates bookmark notes, tags, favorite status, and archives/restores bookmarks via `PATCH` and dedicated action endpoints.
4. Shuts down Server 1 cleanly (`server.shutdown()`, `server.server_close()`).
5. Verifies database file integrity directly using the `sqlite3` module, including `notes` stored as `TEXT`, `tags` stored as JSON array, `is_favorite` stored as `0` or `1`, and `archived` stored as `INTEGER` (`0` or `1`).
6. Verifies automatic SQLite backward-compatibility migrations: opening legacy databases lacking `notes`, `tags`, `is_favorite`, or `archived` columns automatically executes `ALTER TABLE` to add the missing columns with correct default values.
7. Starts Server 2 pointing to the same `db_path` on a new ephemeral port.
8. Verifies all previously created bookmarks, updated notes, tags, favorite status, archive status, and timestamps persist and are queryable via `GET /api/bookmarks` and filtered queries (`?archived=true`, `?archived=all`).
9. Shuts down Server 2 and cleans up temporary database files.

---

### 7.2 Standalone 12-Step Smoke Test: `scripts/smoke_test.py`

`scripts/smoke_test.py` is a standalone executable Python script that executes an end-to-end verification scenario against an ephemeral server instance. It prints deterministic progress logs for each step and exits with status code `0` on total success or non-zero on any assertion failure.

#### The 12 Deterministic Steps:
1. **Step 1 - Server Bootstrap**: Start `create_server(host='127.0.0.1', port=0, db_path=temp_db)` on an ephemeral port; acquire bound port.
2. **Step 2 - Health Check**: Send `GET /health`; assert HTTP 200 and payload `{"status": "ok"}`.
3. **Step 3 - Initial Empty State**: Send `GET /api/bookmarks`; assert HTTP 200 and payload is an empty list `[]`.
4. **Step 4 - Create Bookmark (Valid)**: Send `POST /api/bookmarks` with `{"title": "Python Docs", "url": "https://docs.python.org", "notes": "Official Docs", "tags": ["docs", "python"]}`; assert HTTP 201, `id` is positive integer, `notes` is `"Official Docs"`, `tags` is `["docs", "python"]`, `is_favorite` defaults to `False`, `archived` defaults to `False`, fields match, and timestamps are populated.
5. **Step 5 - Create Bookmark Validation Errors**: Send `POST /api/bookmarks` with invalid payloads (empty title, non-string notes, invalid tags, non-boolean flags); assert HTTP 400.
6. **Step 6 - Verify Bookmark Listing**: Send `GET /api/bookmarks`; assert HTTP 200 and list contains exactly 1 bookmark matching Step 4 with `notes: "Official Docs"`, `tags: ["docs", "python"]`, and `archived: false`.
7. **Step 7 - Search & Tag Filtering**: Send `GET /api/bookmarks?q=Python`; assert HTTP 200 with 1 result. Send `GET /api/bookmarks?q=Docs` (matching notes); assert HTTP 200 with 1 result. Send `GET /api/bookmarks?tag=python`; assert HTTP 200 with 1 result. Send `GET /api/tags`; assert HTTP 200 with `{"tags": ["docs", "python"]}`. Send `GET /api/bookmarks?q=NonExistentTerm`; assert HTTP 200 with 0 results.
8. **Step 8 - Update Bookmark, Notes & Favorite**: Send `PATCH /api/bookmarks/<id>` with `{"notes": "Updated Documentation Notes", "is_favorite": true}`; assert HTTP 200, `notes` updated, `is_favorite` is `True`, `updated_at` updated. Also verify `GET /api/bookmarks?favorites=true` returns the bookmark.
9. **Step 8b - Archive & Restore Semantics**: Send `POST /api/bookmarks/<id>/archive`; assert HTTP 200 and `archived: true`. Verify default `GET /api/bookmarks` returns 0 items. Verify `GET /api/bookmarks?archived=true` and `?archived=all` return the bookmark. Send `POST /api/bookmarks/<id>/restore`; assert HTTP 200 and `archived: false`. Verify default `GET /api/bookmarks` returns the bookmark again. Verify 404 for non-existent IDs.
10. **Step 9 - Update Non-Existent Bookmark**: Send `PATCH /api/bookmarks/99999` with `{"notes": "Ghost"}`; assert HTTP 404.
11. **Step 10 - Delete Bookmark**: Send `DELETE /api/bookmarks/<id>`; assert HTTP 200 and payload `{"status": "deleted", "id": <id>}`. Verify SQLite record is deleted.
12. **Step 11 - Delete Non-Existent Bookmark**: Send `DELETE /api/bookmarks/99999`; assert HTTP 404.
13. **Step 12 - Verify Static Asset Delivery**: Send `GET /`, `GET /style.css`, `GET /app.js`; assert HTTP 200 for all three with appropriate non-empty responses.

*Cleanup*: After Step 12 completes, shut down the server thread and remove temporary database files.

---

## 8. Repository Layout & File Mapping

```
examples/minilinks/
├── SPEC.md                    # Complete MiniLinks product & architectural specification (this document)
├── app/
│   ├── __init__.py            # Python package marker
│   ├── database.py            # SQLite schema initialization, notes, tags, favorite, and archive operations
│   └── server.py              # HTTP request handler, routing, validation, static files, and create_server factory
├── web/
│   ├── index.html             # Responsive bookmark manager HTML interface with archive filter button
│   ├── style.css              # Modern responsive CSS styling including card-notes, archive buttons, badges, and modals
│   └── app.js                 # Vanilla JavaScript API client, card rendering, archive actions, and modal editor
├── tests/
│   ├── __init__.py            # Test package marker
│   ├── test_api.py            # unittest suite for REST API endpoints, archive CRUD/filters, notes, & static files
│   └── test_persistence.py    # unittest suite for database restart persistence including archive column migration
└── scripts/
    └── smoke_test.py          # Standalone 12-step deterministic smoke verification
```

---

## 9. Deterministic Quality Gates & Verification Matrix

Before code is accepted or merged, the following automated checks must pass:
1. **Compilation Check**: `python3 -m compileall app tests scripts` passes with zero syntax errors.
2. **Unit Test Suite**: `python3 -m unittest discover -s tests -p "test_*.py"` completes with 100% passing tests.
3. **Smoke Test Execution**: `python3 scripts/smoke_test.py` completes all deterministic verification steps and exits with status 0.
