"""HTTP server and request handling for MiniBoard Kanban application."""

import http.server
import json
import mimetypes
import os
import sys
import threading
import urllib.parse
from typing import Any, Optional, Tuple

try:
    from .database import (
        DEFAULT_STATUS,
        VALID_STATUSES,
        create_task,
        delete_task,
        get_all_tasks,
        get_task,
        init_db,
        update_task,
    )
except ImportError:
    from database import (
        DEFAULT_STATUS,
        VALID_STATUSES,
        create_task,
        delete_task,
        get_all_tasks,
        get_task,
        init_db,
        update_task,
    )


class MiniBoardHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP request handler implementing the MiniBoard REST API and static assets."""

    server_version = "MiniBoard/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default console logging to keep test output clean."""
        pass

    def _send_json(self, status_code: int, data: Any) -> None:
        """Send a JSON formatted HTTP response with correct headers."""
        self.close_connection = True
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_plain(self, status_code: int, message: str) -> None:
        """Send a plain text HTTP response."""
        self.close_connection = True
        payload = message.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json_body(self) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        """Read and parse the JSON request body. Return (data, error_message)."""
        content_length_header = self.headers.get("Content-Length")
        if not content_length_header:
            return None, "Missing Content-Length"
        try:
            length = int(content_length_header)
            if length <= 0:
                return None, "Empty body"
            raw_data = self.rfile.read(length)
            body = json.loads(raw_data.decode("utf-8"))
            if not isinstance(body, dict):
                return None, "Payload must be a JSON object"
            return body, None
        except Exception as e:
            return None, str(e)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.close_connection = True
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        """Dispatch GET requests for API endpoints and static file serving."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Health check endpoint: GET /health
        if path in ("/health", "/health/"):
            self._send_json(200, {"status": "ok"})
            return

        # 2. Tasks listing endpoint: GET /api/tasks
        if path in ("/api/tasks", "/api/tasks/"):
            tasks = get_all_tasks(self.server.db_path)
            self._send_json(200, tasks)
            return

        # 3. Single task retrieval: GET /api/tasks/<id>
        if path.startswith("/api/tasks/"):
            id_part = path[len("/api/tasks/"):].rstrip("/")
            try:
                task_id = int(id_part)
                if task_id <= 0:
                    raise ValueError()
            except ValueError:
                self._send_json(400, {"error": "Invalid task ID"})
                return

            task = get_task(self.server.db_path, task_id)
            if task is None:
                self._send_json(404, {"error": "Task not found"})
            else:
                self._send_json(200, task)
            return

        # 4. Unknown API paths return 404 JSON
        if path == "/api" or path.startswith("/api/"):
            self._send_json(404, {"error": "Not Found"})
            return

        # 5. Static file serving from web_dir
        self._serve_static_file(path)

    def _serve_static_file(self, raw_path: str) -> None:
        """Serve static files safely from self.server.web_dir."""
        decoded_path = urllib.parse.unquote(raw_path)

        # Reject path traversal attempts
        parts = [p for p in decoded_path.replace("\\", "/").split("/") if p]
        if ".." in parts:
            self._send_plain(403, "Forbidden")
            return

        rel_path = decoded_path.lstrip("/")
        if rel_path == "" or rel_path == "index.html":
            rel_path = "index.html"

        base_web_dir = os.path.abspath(self.server.web_dir)
        target_path = os.path.abspath(os.path.join(base_web_dir, rel_path))

        # Security check: must reside inside base_web_dir
        if not (target_path == base_web_dir or target_path.startswith(base_web_dir + os.sep)):
            self._send_plain(403, "Forbidden")
            return

        if not os.path.isfile(target_path):
            self._send_plain(404, "Not Found")
            return

        # Determine MIME type
        content_type = "application/octet-stream"
        if target_path.endswith(".html"):
            content_type = "text/html; charset=utf-8"
        elif target_path.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif target_path.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        elif target_path.endswith(".json"):
            content_type = "application/json; charset=utf-8"
        else:
            guessed, _ = mimetypes.guess_type(target_path)
            if guessed:
                content_type = guessed

        try:
            with open(target_path, "rb") as f:
                content = f.read()
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self._send_plain(404, "Not Found")

    def do_POST(self) -> None:
        """Handle POST requests to create new tasks."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path not in ("/api/tasks", "/api/tasks/"):
            self._send_json(404, {"error": "Not Found"})
            return

        body, error = self._read_json_body()
        if body is None:
            self._send_json(400, {"error": "Title is required and must be a non-empty string"})
            return

        title = body.get("title")
        if not isinstance(title, str) or not title.strip():
            self._send_json(400, {"error": "Title is required and must be a non-empty string"})
            return

        status = body.get("status", DEFAULT_STATUS)
        if status not in VALID_STATUSES:
            self._send_json(400, {"error": f"Invalid status: {status}. Must be one of {VALID_STATUSES}"})
            return

        try:
            task = create_task(self.server.db_path, title=title, status=status)
            self._send_json(201, task)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})

    def do_PATCH(self) -> None:
        """Handle PATCH requests to partially update an existing task."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ("/api/tasks", "/api/tasks/"):
            self._send_json(400, {"error": "Invalid update payload"})
            return

        if not path.startswith("/api/tasks/"):
            self._send_json(404, {"error": "Not Found"})
            return

        id_part = path[len("/api/tasks/"):].rstrip("/")
        try:
            task_id = int(id_part)
            if task_id <= 0:
                raise ValueError()
        except ValueError:
            self._send_json(400, {"error": "Invalid update payload"})
            return

        body, error = self._read_json_body()
        if body is None:
            self._send_json(400, {"error": "Invalid update payload"})
            return

        has_title = "title" in body
        has_status = "status" in body

        if not has_title and not has_status:
            self._send_json(400, {"error": "Invalid update payload"})
            return

        new_title: Optional[str] = None
        if has_title:
            title_val = body["title"]
            if not isinstance(title_val, str) or not title_val.strip():
                self._send_json(400, {"error": "Invalid update payload"})
                return
            new_title = title_val.strip()

        new_status: Optional[str] = None
        if has_status:
            status_val = body["status"]
            if status_val not in VALID_STATUSES:
                self._send_json(400, {"error": "Invalid update payload"})
                return
            new_status = status_val

        # Check if task exists before updating
        existing_task = get_task(self.server.db_path, task_id)
        if existing_task is None:
            self._send_json(404, {"error": "Task not found"})
            return

        try:
            updated_task = update_task(
                self.server.db_path,
                task_id=task_id,
                title=new_title,
                status=new_status,
            )
            if updated_task is None:
                self._send_json(404, {"error": "Task not found"})
            else:
                self._send_json(200, updated_task)
        except ValueError:
            self._send_json(400, {"error": "Invalid update payload"})

    def do_DELETE(self) -> None:
        """Handle DELETE requests to delete an existing task."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ("/api/tasks", "/api/tasks/"):
            self._send_json(400, {"error": "Invalid task ID"})
            return

        if not path.startswith("/api/tasks/"):
            self._send_json(404, {"error": "Not Found"})
            return

        id_part = path[len("/api/tasks/"):].rstrip("/")
        try:
            task_id = int(id_part)
            if task_id <= 0:
                raise ValueError()
        except ValueError:
            self._send_json(400, {"error": "Invalid task ID"})
            return

        deleted = delete_task(self.server.db_path, task_id)
        if not deleted:
            self._send_json(404, {"error": "Task not found"})
            return

        self._send_json(200, {"status": "deleted", "id": task_id})


class MiniBoardServer(http.server.HTTPServer):
    """Custom HTTPServer maintaining configuration for SQLite db_path and static web_dir."""

    allow_reuse_address = True
    request_queue_size = 128

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: type,
        db_path: str,
        web_dir: str,
    ) -> None:
        self.db_path = db_path
        self.web_dir = web_dir
        super().__init__(server_address, RequestHandlerClass)
        self.server_port: int = self.server_address[1]


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    db_path: str = "miniboard.db",
    web_dir: Optional[str] = None,
) -> Tuple[http.server.HTTPServer, threading.Thread]:
    """
    Initializes the SQLite database at `db_path`, instantiates an HTTPServer
    bound to (host, port), and starts listening inside a background daemon thread.

    Parameters:
        host (str): Hostname or IP to bind (default: '127.0.0.1').
        port (int): Port number (default: 0 for OS-assigned ephemeral port).
        db_path (str): File system path to the SQLite database.
        web_dir (Optional[str]): Path to static web directory. Defaults to repo 'web/' directory.

    Returns:
        tuple[http.server.HTTPServer, threading.Thread]:
            - server: The running HTTPServer instance (exposing server_port, server_address, shutdown).
            - thread: The daemon threading.Thread executing server.serve_forever().
    """
    if web_dir is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        web_dir = os.path.join(repo_root, "web")

    init_db(db_path)

    server = MiniBoardServer(
        (host, port),
        MiniBoardHandler,
        db_path=db_path,
        web_dir=web_dir,
    )

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, thread


if __name__ == "__main__":
    bind_host = os.environ.get("HOST", "127.0.0.1")
    bind_port = int(os.environ.get("PORT", "8000"))
    database_file = os.environ.get("DB_PATH", "miniboard.db")

    srv, th = create_server(host=bind_host, port=bind_port, db_path=database_file)
    print(f"MiniBoard server listening on http://{srv.server_address[0]}:{srv.server_port}")
    try:
        th.join()
    except KeyboardInterrupt:
        print("\nStopping MiniBoard server...")
        srv.shutdown()
        srv.server_close()
