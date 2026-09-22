# Worker Operating Instructions

You are an automated software engineering worker executing a targeted task within an isolated Git worktree.

## Strict Operational Guardrails

1. **Assigned Workspace**: You MUST operate exclusively within the provided worktree directory: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223926/wave1_tests`. Never access or modify any files outside this directory.
2. **Allowed Paths**: You may ONLY create or modify files matching the following allowed path pattern(s):
- `tests/**`
- `scripts/**`
Modifying any out-of-scope files will result in an immediate rejection of your work.
3. **No Package Installation**: DO NOT install any packages or dependencies. Do NOT run `pip`, `npm`, `apt`, `brew`, or any other package manager.
4. **No Environment Mutation**: DO NOT alter or create `.venv`, do NOT modify `.agy-factory`, do NOT touch Herdr settings or sessions, and do NOT alter user/global configuration or authentication.
5. **No Version Control Manipulation**: DO NOT run `git commit`, `git push`, `git branch`, `git merge`, or `git worktree`. Git lifecycle, integration, and commits are owned exclusively by the factory orchestrator.
6. **Tool Usage — STRICTLY NO SHELL EXECUTION**:
   - You MUST use the `write_to_file` and `replace_file_content` tools to create and edit code.
   - When calling `write_to_file`, `TargetFile` MUST be the full absolute path: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223926/wave1_tests/<relative_path>`.
   - DO NOT call the `run_command` tool. Shell command execution is prohibited and will be denied automatically.
7. **Implementation Quality**: Follow the committed specification and API contract strictly. Ensure standard library compliance only (Python 3 stdlib, SQLite, vanilla HTML/CSS/JS).

## Task Description
Implement comprehensive stdlib tests in tests/test_api.py, tests/test_persistence.py, and standalone smoke script in scripts/smoke_test.py. Tests must use unittest, tempfile, urllib, sqlite3, threading. Verify /health, CRUD on /api/tasks, invalid payload error handling, and database persistence across server restart on ephemeral port.

## Committed Product Specification (docs/SPECIFICATION.md)
```markdown
# MiniBoard Product Specification

## 1. Executive Summary & Overview

**MiniBoard** is a zero-dependency, lightweight, single-user Kanban task management application designed for local operation. It provides an intuitive web-based interface organized around three status columns—`TODO`, `DOING`, and `DONE`—backed by a robust, standard-library-only Python HTTP server and SQLite database storage.

### Core Architectural Principles
- **Zero Third-Party Dependencies**: Built strictly using the Python 3 standard library (`http.server`, `sqlite3`, `json`, `urllib`, `unittest`, `threading`) and standard web technologies (vanilla HTML5, CSS3, and modern ES6+ JavaScript).
- **Process & Test Isolation**: Headless server instantiation with configurable host, ephemeral port binding (`port=0`), and isolated database paths to enable concurrent execution and automated testing without port collisions or file locks.
- **Contract Determinism**: Explicit REST API endpoints, strict schema validation, predictable HTTP status codes, and unambiguous data contracts.
- **Persistence Integrity**: Atomic, ACID-compliant persistence using SQLite with transactional operations and integrity constraints.

---

## 2. SQLite Database Schema

The database persists tasks in a single SQLite table named `tasks`.

### 2.1 Table Definition: `tasks`

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('TODO', 'DOING', 'DONE')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 2.2 Column Specifications

| Column Name | SQLite Type | Constraints | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique identifier generated sequentially by SQLite. | `1` |
| `title` | `TEXT` | `NOT NULL` | The task description/title. Cannot be NULL or empty string. | `"Implement SQLite schema"` |
| `status` | `TEXT` | `NOT NULL CHECK(status IN ('TODO', 'DOING', 'DONE'))` | Current workflow state of the task. Strictly limited to the three allowed column identifiers. | `"TODO"` |
| `created_at`| `TEXT` | `NOT NULL` | ISO 8601 UTC timestamp recorded when the task record is first inserted. | `"2026-09-23T00:00:00Z"` |
| `updated_at`| `TEXT` | `NOT NULL` | ISO 8601 UTC timestamp updated on initial creation and every subsequent modification. | `"2026-09-23T00:05:00Z"` |

### 2.3 Status Transition Rules
- Valid status values are strictly: `'TODO'`, `'DOING'`, `'DONE'`.
- Any attempt to insert or update a task with a status outside this set must fail with a validation error (`400 Bad Request` at the API layer; SQLite constraint violation at the storage layer).
- Default status for newly created tasks is `'TODO'` if not specified in the payload.

### 2.4 Timestamp Standards
- Timestamps must follow ISO-8601 format in UTC: `YYYY-MM-DDTHH:MM:SSZ` or standard Python `datetime.now(datetime.timezone.utc).isoformat()`.

---

## 3. REST API Contract

All API endpoints return JSON payloads (`Content-Type: application/json; charset=utf-8`) unless serving static assets. Request bodies must be valid JSON when payload is expected.

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

### 3.2 `GET /api/tasks`
Retrieves all tasks ordered by `id ASC` (or `created_at ASC`).

- **Request**:
  - Method: `GET`
  - Path: `/api/tasks`
- **Response**:
  - Status: `200 OK`
  - Body: Array of task objects. If no tasks exist, returns an empty list `[]`.
    ```json
    [
      {
        "id": 1,
        "title": "Set up project structure",
        "status": "DONE",
        "created_at": "2026-09-23T00:00:00Z",
        "updated_at": "2026-09-23T00:05:00Z"
      },
      {
        "id": 2,
        "title": "Write API unit tests",
        "status": "DOING",
        "created_at": "2026-09-23T00:01:00Z",
        "updated_at": "2026-09-23T00:06:00Z"
      }
    ]
    ```

---

### 3.3 `POST /api/tasks`
Creates a new task.

- **Request**:
  - Method: `POST`
  - Path: `/api/tasks`
  - Headers: `Content-Type: application/json`
  - Body:
    ```json
    {
      "title": "Implement drag and drop",
      "status": "TODO"
    }
    ```
    - `title` (required, `string`): Non-empty, trimmed title.
    - `status` (optional, `string`): Must be one of `"TODO"`, `"DOING"`, `"DONE"`. Defaults to `"TODO"` if omitted.
- **Success Response**:
  - Status: `201 Created`
  - Body: Complete task object with generated `id`, `created_at`, and `updated_at`.
    ```json
    {
      "id": 3,
      "title": "Implement drag and drop",
      "status": "TODO",
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:10:00Z"
    }
    ```
- **Error Responses**:
  - Status: `400 Bad Request`
  - Conditions: Missing body, invalid JSON syntax, missing `title`, empty/whitespace-only `title`, `title` is not a string, or invalid `status` value.
  - Body:
    ```json
    {
      "error": "Title is required and must be a non-empty string"
    }
    ```

---

### 3.4 `PATCH /api/tasks/<id>`
Partially updates an existing task's `title`, `status`, or both.

- **Request**:
  - Method: `PATCH`
  - Path: `/api/tasks/<id>` where `<id>` is a positive integer.
  - Headers: `Content-Type: application/json`
  - Body: JSON containing one or both fields:
    ```json
    {
      "status": "DOING"
    }
    ```
    or
    ```json
    {
      "title": "Updated task title"
    }
    ```
    or
    ```json
    {
      "title": "Updated task title",
      "status": "DONE"
    }
    ```
- **Success Response**:
  - Status: `200 OK`
  - Body: Complete updated task object with new `updated_at` timestamp.
    ```json
    {
      "id": 3,
      "title": "Updated task title",
      "status": "DONE",
      "created_at": "2026-09-23T00:10:00Z",
      "updated_at": "2026-09-23T00:15:00Z"
    }
    ```
- **Error Responses**:
  - Status: `404 Not Found`
    - Condition: Task with specified `id` does not exist.
    - Body:
      ```json
      {
        "error": "Task not found"
      }
      ```
  - Status: `400 Bad Request`
    - Conditions: Invalid integer in URL path, invalid JSON body, no updatable fields provided, invalid `status` (not one of `"TODO"`, `"DOING"`, `"DONE"`), or empty/whitespace-only `title`.
    - Body:
      ```json
      {
        "error": "Invalid update payload"
      }
      ```

---

### 3.5 `DELETE /api/tasks/<id>`
Deletes a task by ID.

- **Request**:
  - Method: `DELETE`
  - Path: `/api/tasks/<id>` where `<id>` is a positive integer.
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
    - Condition: Task with specified `id` does not exist.
    - Body:
      ```json
      {
        "error": "Task not found"
      }
      ```
  - Status: `400 Bad Request`
    - Condition: Non-integer `<id>`.
    - Body:
      ```json
      {
        "error": "Invalid task ID"
      }
      ```

---

## 4. Static File Serving Specification

The backend server serves static front-end assets located in the `web/` directory:
- `/` or `/index.html` $\rightarrow$ `web/index.html` (`Content-Type: text/html; charset=utf-8`)
- `/style.css` $\rightarrow$ `web/style.css` (`Content-Type: text/css; charset=utf-8`)
- `/app.js` $\rightarrow$ `web/app.js` (`Content-Type: application/javascript; charset=utf-8`)

### Security & Path Handling
- Paths must be resolved relative to the designated `web/` directory.
- Directory traversal attacks (e.g., `../`, `..%2F`) must be rejected with `403 Forbidden` or `404 Not Found`.
- Non-existent static files must return `404 Not Found`.

---

## 5. Python Backend Architecture & Programmatic Interface

### 5.1 Module Structure
- `app/database.py`: Encapsulates SQLite connection management, schema creation, and task CRUD helper functions.
- `app/server.py`: Implements custom `http.server.BaseHTTPRequestHandler` routing, request dispatching, JSON serialization, and the programmatic factory function `create_server`.

### 5.2 Server Factory Interface: `create_server`

```python
def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    db_path: str = "miniboard.db"
) -> tuple[http.server.HTTPServer, threading.Thread]:
    """
    Initializes the SQLite database at `db_path`, instantiates an HTTPServer
    bound to (host, port), and starts listening inside a background daemon thread.

    Parameters:
        host (str): Hostname or IP to bind (default: '127.0.0.1').
        port (int): Port number (default: 0 for OS-assigned ephemeral port).
        db_path (str): File system path to the SQLite database.

    Returns:
        tuple[http.server.HTTPServer, threading.Thread]:
            - server: The running HTTPServer instance (exposing server_port, server_address, shutdown).
            - thread: The daemon threading.Thread executing server.serve_forever().
    """
```

### 5.3 Lifecycle & Teardown Requirements
- Daemon Thread: The server thread must be configured with `daemon=True` so it does not block Python process termination.
- Ephemeral Port Resolution: When `port=0` is supplied, callers can retrieve the assigned port via `server.server_port` or `server.server_address[1]`.
- Clean Shutdown: Calling `server.shutdown()` followed by `server.server_close()` must stop the server and release the bound socket immediately without deadlocks.

---

## 6. Frontend Architecture & UI/UX Requirements

The frontend lives in `web/` and consists of three standard files:
- `web/index.html`: Semantic HTML structure.
- `web/style.css`: Clean, modern, responsive CSS styling.
- `web/app.js`: Vanilla JavaScript logic communicating with the REST API.

### 6.1 Layout & Columns
- **Header**: MiniBoard title, quick statistics (e.g., total tasks count), and an operational status/notification banner.
- **Task Creation Form**: Input bar with a text input (`id="task-title-input"`) and an "Add Task" button (`id="task-submit-btn"`). Submitting (via button click or pressing Enter) creates a new task in `TODO` status.
- **Kanban Board Grid**: Responsive 3-column layout:
  1. `TODO` column (`id="col-todo"`)
  2. `DOING` column (`id="col-doing"`)
  3. `DONE` column (`id="col-done"`)
- Responsive Design: Flexible grid / flexbox adapting gracefully between mobile screens (single-column stacking) and desktop screens (three side-by-side columns).

### 6.2 Task Card Elements & Interactions
Each task card rendered within a column must display:
- **Task Title**: Text display with option to edit inline or via a modal/prompt.
- **Timestamp / Metadata**: Display created or updated timestamp.
- **Action Controls**:
  - Forward / Back Buttons or Status Transition dropdown (e.g. Move to DOING / Move to DONE / Move to TODO) to trigger `PATCH /api/tasks/<id>`.
  - Optional drag-and-drop support between columns.
  - Delete Button: Button to delete the task via `DELETE /api/tasks/<id>`, removing the card from the UI.
- **Feedback & Notifications**: Visual banners or toast alerts for API failures, validation errors, and network disconnects.

---

## 7. Testing Requirements & Test Harness

Testing is implemented strictly using Python's standard library `unittest` and `urllib.request`. Tests must not depend on external test runners or libraries.

### 7.1 Unit & Integration Test Suites in `tests/`

#### 7.1.1 `tests/test_api.py`
Validates all HTTP API endpoints against a live server running on an ephemeral port with an isolated temporary SQLite database:
1. Server bootstrap and `GET /health` responding with `{"status": "ok"}`.
2. Initial task listing `GET /api/tasks` returning `[]`.
3. Creating tasks via `POST /api/tasks` with valid and invalid payloads (empty title, missing fields, invalid status).
4. Updating tasks via `PATCH /api/tasks/<id>` for title and status transitions.
5. Error responses: verifying `400 Bad Request` on malformed JSON and `404 Not Found` for non-existent IDs.
6. Deletion via `DELETE /api/tasks/<id>` verifying removal and subsequent 404 responses.
7. Static file serving: verifying retrieval of `/`, `/style.css`, and `/app.js` with appropriate MIME types.

#### 7.1.2 `tests/test_persistence.py`
Validates SQLite persistence across server lifecycle restarts:
1. Starts Server 1 on ephemeral port with `db_path=temp_db.db`.
2. Inserts tasks into Server 1 via `POST /api/tasks`.
3. Shuts down Server 1 (`shutdown()`, `server_close()`).
4. Verifies database file integrity directly via `sqlite3` standard library module.
5. Starts Server 2 pointing to the same `db_path=temp_db.db` on a new ephemeral port.
6. Verifies all previously created tasks and their updated statuses are intact and queryable via `GET /api/tasks`.
7. Shuts down Server 2 and cleans up temporary files.

---

### 7.2 Standalone 12-Step Smoke Test: `scripts/smoke_test.py`

`scripts/smoke_test.py` is a standalone executable Python script that runs an end-to-end verification scenario against an ephemeral server instance. It must output clear progress logs for each step and exit with code `0` on total success or non-zero on any failure.

#### The 12 Deterministic Steps:
1. **Step 1 - Server Bootstrap**: Start `create_server(host='127.0.0.1', port=0, db_path=temp_db)` on an ephemeral port; acquire bound port.
2. **Step 2 - Health Check**: Send `GET /health`; assert HTTP 200 and payload `{"status": "ok"}`.
3. **Step 3 - Initial Empty State**: Send `GET /api/tasks`; assert HTTP 200 and payload is an empty list `[]`.
4. **Step 4 - Create Task (Valid)**: Send `POST /api/tasks` with `{"title": "Smoke Task 1", "status": "TODO"}`; assert HTTP 201, `id` is positive integer, `status == "TODO"`, and timestamps are populated.
5. **Step 5 - Create Task Validation Error**: Send `POST /api/tasks` with invalid payload `{"title": ""}`; assert HTTP 400.
6. **Step 6 - Verify Task Listing**: Send `GET /api/tasks`; assert HTTP 200 and list contains exactly 1 task matching Task 1.
7. **Step 7 - Update Status**: Send `PATCH /api/tasks/<id>` with `{"status": "DOING"}`; assert HTTP 200 and `status == "DOING"`.
8. **Step 8 - Update Title**: Send `PATCH /api/tasks/<id>` with `{"title": "Smoke Task 1 Updated"}`; assert HTTP 200 and `title == "Smoke Task 1 Updated"`.
9. **Step 9 - Update Non-Existent Task**: Send `PATCH /api/tasks/99999` with `{"status": "DONE"}`; assert HTTP 404.
10. **Step 10 - Delete Task**: Send `DELETE /api/tasks/<id>`; assert HTTP 200 and payload `{"status": "deleted", "id": <id>}`.
11. **Step 11 - Delete Non-Existent Task**: Send `DELETE /api/tasks/99999`; assert HTTP 404.
12. **Step 12 - Verify Static Asset Delivery**: Send `GET /`, `GET /style.css`, `GET /app.js`; assert HTTP 200 for all three with appropriate non-empty responses.

*Cleanup*: After Step 12 completes, shut down the server thread and remove temporary database files.

---

## 8. Repository Layout & File Mapping

```
.
├── docs/
│   └── SPECIFICATION.md       # Product & architectural specification (this document)
├── app/
│   ├── __init__.py            # Python package marker
│   ├── database.py            # SQLite schema initialization and query operations
│   └── server.py              # HTTP request handler and create_server factory
├── web/
│   ├── index.html             # Kanban board HTML structure
│   ├── style.css              # Modern responsive styling
│   └── app.js                 # Frontend API client and DOM interaction
├── tests/
│   ├── __init__.py            # Test package marker
│   ├── test_api.py            # unittest suite for REST endpoints & static files
│   └── test_persistence.py    # unittest suite for database restart persistence
└── scripts/
    └── smoke_test.py          # Standalone 12-step deterministic smoke verification
```

---

## 9. Deterministic Quality Gates & Verification Matrix

Before code is accepted or merged, the following automated checks are applied:
1. **Compilation Check**: `python3 -m compileall app tests scripts` passes with zero syntax errors.
2. **Unit Test Suite**: `python3 -m unittest discover -s tests -p "test_*.py"` completes with 100% passing tests.
3. **Smoke Test Execution**: `python3 scripts/smoke_test.py` completes all 12 steps and exits with status 0.

```


### Required TargetFile Paths to Create via write_to_file:
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223926/wave1_tests/tests/test_api.py`
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223926/wave1_tests/tests/test_persistence.py`
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223926/wave1_tests/scripts/smoke_test.py`


## Required Structured Output
You must return a valid JSON object matching the worker result schema:
```json
{
  "task_id": "wave1_tests",
  "status": "COMPLETED",
  "summary": "<clear summary of what was implemented>",
  "changed_files": ["<list of relative paths created or modified>"],
  "notes": "<optional design notes or considerations>"
}
```
