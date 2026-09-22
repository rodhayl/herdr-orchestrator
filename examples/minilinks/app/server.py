"""HTTP server, request routing, and server factory for MiniLinks."""

import http.server
import json
import mimetypes
from pathlib import Path
import threading
from typing import Any, Dict, Optional, Tuple, Union
import urllib.parse

try:
    from . import database
except ImportError:
    import database

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


def is_valid_url(url: Any) -> bool:
    """
    Validates that a URL is a non-empty string starting with http:// or https://
    and contains a valid network location (host).
    """
    if not isinstance(url, str):
        return False
    stripped = url.strip()
    if not (stripped.startswith("http://") or stripped.startswith("https://")):
        return False
    try:
        parsed = urllib.parse.urlparse(stripped)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


class MiniLinksServer(http.server.HTTPServer):
    """Custom HTTPServer maintaining database path and web directory configuration."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: type,
        db_path: str = database.DEFAULT_DB_PATH,
        web_dir: Optional[Union[str, Path]] = None,
    ):
        self.db_path = db_path
        if web_dir is not None:
            self.web_dir = Path(web_dir).resolve()
        else:
            self.web_dir = WEB_DIR.resolve()
        super().__init__(server_address, RequestHandlerClass)
        self.server_port: int = self.server_address[1]


class MiniLinksHandler(http.server.BaseHTTPRequestHandler):
    """Request handler implementing the MiniLinks REST API and static asset delivery."""

    server: MiniLinksServer

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default console logging to keep test output clean."""
        pass

    def send_json(self, status_code: int, data: Any) -> None:
        """Sends a JSON-formatted HTTP response."""
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def send_json_error(self, status_code: int, message: str) -> None:
        """Sends a JSON error response with an 'error' field."""
        self.send_json(status_code, {"error": message})

    def read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Reads and parses the JSON request body.
        Returns (parsed_dict, None) on success, or (None, error_message) on failure.
        """
        content_length_header = self.headers.get("Content-Length")
        if not content_length_header:
            return None, "Missing request body"
        try:
            content_length = int(content_length_header)
        except ValueError:
            return None, "Invalid Content-Length header"

        if content_length <= 0:
            return None, "Empty request body"

        try:
            raw_body = self.rfile.read(content_length)
            data = json.loads(raw_body.decode("utf-8"))
        except Exception as e:
            return None, f"Malformed JSON: {e}"

        if not isinstance(data, dict):
            return None, "JSON body must be an object"

        return data, None

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS"
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Handles GET requests: /health, /api/bookmarks, and static files."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "":
            path = "/"

        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        if path == "/api/bookmarks":
            query_params = urllib.parse.parse_qs(parsed.query)
            q_list = query_params.get("q")
            q = q_list[0] if q_list else None
            bookmarks = database.get_bookmarks(q=q, db_path=self.server.db_path)
            self.send_json(200, bookmarks)
            return

        if path.startswith("/api/bookmarks/"):
            id_str = path[len("/api/bookmarks/"):]
            if "/" not in id_str and id_str != "":
                try:
                    bm_id = int(id_str)
                    if bm_id <= 0:
                        raise ValueError()
                except ValueError:
                    self.send_json_error(400, "Invalid bookmark ID")
                    return

                bm = database.get_bookmark_by_id(bm_id, db_path=self.server.db_path)
                if bm is None:
                    self.send_json_error(404, "Bookmark not found")
                    return
                self.send_json(200, bm)
                return

        if path.startswith("/api/"):
            self.send_json_error(404, "Endpoint not found")
            return

        # Static file delivery
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        """Handles POST requests: creating bookmarks at /api/bookmarks."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path != "/api/bookmarks":
            if path.startswith("/api/"):
                self.send_json_error(404, "Endpoint not found")
            else:
                self.send_error(405, "Method Not Allowed")
            return

        body, err = self.read_json_body()
        if err or body is None:
            self.send_json_error(
                400, "Both 'title' and 'url' are required non-empty strings"
            )
            return

        title = body.get("title")
        url = body.get("url")
        notes = body.get("notes")

        # Validate title
        if not isinstance(title, str) or not title.strip():
            self.send_json_error(
                400, "Both 'title' and 'url' are required non-empty strings"
            )
            return

        # Validate url
        if not isinstance(url, str) or not url.strip():
            self.send_json_error(
                400, "Both 'title' and 'url' are required non-empty strings"
            )
            return

        if not is_valid_url(url):
            self.send_json_error(
                400, "Invalid URL format. URL must start with http:// or https://"
            )
            return

        # Validate notes
        if notes is not None and not isinstance(notes, str):
            self.send_json_error(400, "Notes must be a string if provided")
            return

        clean_title = title.strip()
        clean_url = url.strip()
        clean_notes = notes if notes is not None else ""

        created = database.create_bookmark(
            title=clean_title,
            url=clean_url,
            notes=clean_notes,
            db_path=self.server.db_path,
        )
        self.send_json(201, created)

    def do_PATCH(self) -> None:
        """Handles PATCH requests: partially updating bookmarks at /api/bookmarks/<id>."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not path.startswith("/api/bookmarks/"):
            if path.startswith("/api/"):
                self.send_json_error(404, "Endpoint not found")
            else:
                self.send_error(405, "Method Not Allowed")
            return

        id_str = path[len("/api/bookmarks/"):]
        if "/" in id_str or id_str == "":
            self.send_json_error(400, "Invalid bookmark ID")
            return

        try:
            bm_id = int(id_str)
            if bm_id <= 0:
                raise ValueError()
        except ValueError:
            self.send_json_error(400, "Invalid bookmark ID")
            return

        body, err = self.read_json_body()
        if err or body is None:
            self.send_json_error(400, "Invalid update payload")
            return

        allowed_fields = {"title", "url", "notes"}
        present_fields = [k for k in body.keys() if k in allowed_fields]
        if not present_fields:
            self.send_json_error(400, "Invalid update payload")
            return

        clean_title: Optional[str] = None
        clean_url: Optional[str] = None
        clean_notes: Optional[str] = None

        if "title" in body:
            title = body["title"]
            if not isinstance(title, str) or not title.strip():
                self.send_json_error(400, "Invalid update payload")
                return
            clean_title = title.strip()

        if "url" in body:
            url = body["url"]
            if not isinstance(url, str) or not url.strip() or not is_valid_url(url):
                self.send_json_error(400, "Invalid update payload")
                return
            clean_url = url.strip()

        if "notes" in body:
            notes = body["notes"]
            if notes is not None and not isinstance(notes, str):
                self.send_json_error(400, "Invalid update payload")
                return
            clean_notes = notes if notes is not None else ""

        existing = database.get_bookmark_by_id(bm_id, db_path=self.server.db_path)
        if existing is None:
            self.send_json_error(404, "Bookmark not found")
            return

        updated = database.update_bookmark(
            id=bm_id,
            title=clean_title,
            url=clean_url,
            notes=clean_notes,
            db_path=self.server.db_path,
        )
        self.send_json(200, updated)

    def do_DELETE(self) -> None:
        """Handles DELETE requests: removing bookmarks at /api/bookmarks/<id>."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not path.startswith("/api/bookmarks/"):
            if path.startswith("/api/"):
                self.send_json_error(404, "Endpoint not found")
            else:
                self.send_error(405, "Method Not Allowed")
            return

        id_str = path[len("/api/bookmarks/"):]
        if "/" in id_str or id_str == "":
            self.send_json_error(400, "Invalid bookmark ID")
            return

        try:
            bm_id = int(id_str)
            if bm_id <= 0:
                raise ValueError()
        except ValueError:
            self.send_json_error(400, "Invalid bookmark ID")
            return

        existing = database.get_bookmark_by_id(bm_id, db_path=self.server.db_path)
        if existing is None:
            self.send_json_error(404, "Bookmark not found")
            return

        success = database.delete_bookmark(id=bm_id, db_path=self.server.db_path)
        if not success:
            self.send_json_error(404, "Bookmark not found")
            return

        self.send_json(200, {"status": "deleted", "id": bm_id})

    def serve_static(self, raw_path: str) -> None:
        """
        Serves static files from the designated web directory with strict
        directory traversal protection.
        """
        parsed = urllib.parse.urlparse(raw_path)
        path_only = parsed.path

        unquoted = urllib.parse.unquote(path_only)
        if "\x00" in unquoted:
            self.send_error(400, "Bad Request")
            return

        # Check for directory traversal sequences
        normalized_path = unquoted.replace("\\", "/")
        segments = [s for s in normalized_path.split("/") if s]
        if ".." in segments:
            self.send_error(403, "Forbidden")
            return

        rel_path = normalized_path.lstrip("/")
        if rel_path == "" or rel_path.endswith("/"):
            rel_path += "index.html"

        web_dir = Path(getattr(self.server, "web_dir", WEB_DIR)).resolve()
        target_path = (web_dir / rel_path).resolve()

        # Ensure the resolved file path is inside web_dir
        try:
            target_path.relative_to(web_dir)
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        if not target_path.is_file():
            self.send_error(404, "Not Found")
            return

        ext = target_path.suffix.lower()
        content_type = MIME_TYPES.get(ext)
        if not content_type:
            guessed, _ = mimetypes.guess_type(str(target_path))
            content_type = guessed or "application/octet-stream"
            if content_type.startswith("text/") and "charset" not in content_type:
                content_type += "; charset=utf-8"

        try:
            with open(target_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    db_path: str = database.DEFAULT_DB_PATH,
    web_dir: Optional[Union[str, Path]] = None,
) -> MiniLinksServer:
    """
    Initializes the SQLite database at `db_path`, instantiates an HTTPServer
    bound to (host, port), and starts listening inside a background daemon thread.

    Parameters:
        host (str): Hostname or IP to bind (default: '127.0.0.1').
        port (int): Port number (default: 0 for OS-assigned ephemeral port).
        db_path (str): File system path to the SQLite database.
        web_dir (str | Path, optional): Custom path to static web assets.

    Returns:
        MiniLinksServer:
            The running HTTPServer instance. The server runs in a daemon thread,
            exposes `server_port` / `server_address` (resolving the ephemeral port),
            and supports clean shutdown via `server.shutdown()` and `server.server_close()`.
    """
    database.init_db(db_path)
    server = MiniLinksServer(
        (host, port),
        MiniLinksHandler,
        db_path=db_path,
        web_dir=web_dir,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="MiniLinks HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind")
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--db",
        default=database.DEFAULT_DB_PATH,
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--web-dir",
        default=str(WEB_DIR),
        help="Path to static web directory",
    )
    args = parser.parse_args()

    srv = create_server(
        host=args.host,
        port=args.port,
        db_path=args.db,
        web_dir=args.web_dir,
    )
    print(f"MiniLinks server listening at http://{args.host}:{srv.server_port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        srv.shutdown()
        srv.server_close()
